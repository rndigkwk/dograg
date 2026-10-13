"""Answer times as a guardian in Korea sees them, on two deployments of the same image.

    uvx --with playwright python scripts/compare_deployment_latency.py URL_A URL_B [--rounds 2]

For each question a fresh browser session opens /rag on each deployment in turn (the order
alternates), asks the question and records:
- page_s: from opening the page until the chat input is ready
- first_s: from sending until the answer's first text (not the progress line)
- done_s: from sending until the answer is finished (feedback buttons shown, input open again)
Both deployments are woken first, so cold starts are not in the numbers. Real model calls.
Prints medians per deployment and per question kind; results: output/experiments/deployment_latency.json.
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
INPUT = 'textarea[data-testid="stChatInputTextArea"]'
MESSAGE = '[data-testid="stChatMessage"]'
QUESTIONS = [
    ("health", "강아지가 이틀째 설사를 해요"), ("health", "강아지가 기침을 계속해요"),
    ("health", "강아지가 밥을 안 먹고 기운이 없어요"), ("health", "강아지 귀에서 냄새가 나요"),
    ("health", "강아지가 다리를 절뚝거려요"), ("health", "심장사상충 약은 얼마나 자주 먹여요?"),
    ("place", "강남구 동물병원 알려줘"), ("place", "마포구 동물약국 찾아줘"),
    ("report", "반려동물 장묘 서비스 이용 실태를 알려줘"), ("report", "반려견 보험 가입률 알려줘"),
    ("fee", "강남구 엑스레이 비용 얼마야?"), ("date", "오늘 날짜 알려줘"),
]


def ask(browser, url: str, question: str) -> dict:
    page = browser.new_context().new_page()
    started = time.perf_counter()
    page.goto(f"{url.rstrip('/')}/rag", wait_until="domcontentloaded")
    page.wait_for_selector(INPUT, timeout=120_000)
    page_s = time.perf_counter() - started
    box = page.locator(INPUT)
    box.fill(question)
    box.press("Enter")
    sent = time.perf_counter()
    first_s = done_s = None
    while time.perf_counter() - sent < 120:
        page.wait_for_timeout(150)
        texts = page.locator(MESSAGE).all_inner_texts()
        last = texts[-1] if len(texts) >= 2 and texts[-1].startswith("smart_toy") else ""
        body = last.replace("smart_toy", "").strip()
        if first_s is None and body and "⏳" not in body:
            first_s = time.perf_counter() - sent
        if "thumb_up" in body and "⏳" not in body and box.is_enabled():  # every answer gets feedback buttons
            done_s = time.perf_counter() - sent
            break
    page.context.close()
    return {"page_s": round(page_s, 2), "first_s": round(first_s, 2) if first_s else None,
            "done_s": round(done_s, 2) if done_s else None}


def main() -> int:
    from playwright.sync_api import sync_playwright

    parser = argparse.ArgumentParser()
    parser.add_argument("url_a")
    parser.add_argument("url_b")
    parser.add_argument("--rounds", type=int, default=2)
    args = parser.parse_args()
    urls = {"A": args.url_a, "B": args.url_b}
    rows = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        for name, url in urls.items():  # wake both; not measured
            print("warm", name, ask(browser, url, "오늘 날짜 알려줘"), flush=True)
        for round_ in range(args.rounds):
            for index, (kind, question) in enumerate(QUESTIONS):
                order = ["A", "B"] if (index + round_) % 2 == 0 else ["B", "A"]
                for name in order:
                    row = {"round": round_, "kind": kind, "question": question, "deployment": name, **ask(browser, urls[name], question)}
                    rows.append(row)
                    print(json.dumps(row, ensure_ascii=False), flush=True)
        browser.close()

    def median(values):
        values = [v for v in values if v is not None]
        return round(statistics.median(values), 2) if values else None

    summary = {}
    for name, url in urls.items():
        mine = [r for r in rows if r["deployment"] == name]
        summary[name] = {"url": url, **{m: median([r[m] for r in mine]) for m in ("page_s", "first_s", "done_s")},
                         "by_kind_done_s": {k: median([r["done_s"] for r in mine if r["kind"] == k]) for k in dict.fromkeys(q[0] for q in QUESTIONS)}}
    pairs = {}
    for r in rows:
        pairs.setdefault((r["round"], r["question"]), {})[r["deployment"]] = r["done_s"]
    diffs = [p["B"] - p["A"] for p in pairs.values() if p.get("A") and p.get("B")]
    summary["done_s_B_minus_A_median"] = median(diffs)
    summary["B_faster_count"] = f"{sum(d < 0 for d in diffs)}/{len(diffs)}"
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    out = PROJECT_DIR / "output" / "experiments" / "deployment_latency.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
