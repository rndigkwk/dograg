"""Memory of the Streamlit server while the visit-prep page runs the team once (real model calls).

Starts `streamlit run main.py`, opens the chat page and waits for the warm-up (the same
resources the deployed app loads), then submits one consultation on the visit-prep page and
samples the server's RSS until the report appears.

    uvx --with playwright --with psutil python scripts/measure_visit_prep_memory.py   # uses .venv's streamlit
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from pathlib import Path

import psutil
from playwright.sync_api import sync_playwright

PROJECT_DIR = Path(__file__).resolve().parents[1]
PORT = 8599
CONSULTATION = "4살 말티즈가 어제부터 설사를 하고 오늘 아침에 두 번 토했어요. 일주일 전에 사료를 바꿨고 기운이 좀 없어요. 병원비가 얼마나 나올지도 걱정돼요."
WARMUP_S = 90


def python_in_venv() -> Path:
    windows = PROJECT_DIR / ".venv" / "Scripts" / "python.exe"
    return windows if windows.exists() else PROJECT_DIR / ".venv" / "bin" / "python"


class RssSampler:
    def __init__(self, process: psutil.Process):
        self.process, self.peak, self.stop = process, 0, threading.Event()
        self.thread = threading.Thread(target=self.loop, daemon=True)

    def rss(self) -> int:
        """The server and its children: on Windows .venv's python.exe is a launcher process."""
        total = 0
        try:
            processes = [self.process, *self.process.children(recursive=True)]
        except psutil.Error:
            return 0
        for process in processes:
            try:
                total += process.memory_info().rss
            except psutil.Error:
                pass
        return total

    def loop(self) -> None:
        while not self.stop.is_set():
            self.peak = max(self.peak, self.rss())
            time.sleep(0.25)

    def mark(self) -> int:
        """Peak since the last mark, then start a new window."""
        peak, self.peak = max(self.peak, self.rss()), self.rss()
        return round(peak / 2**20)


def main() -> int:
    server = subprocess.Popen(
        [str(python_in_venv()), "-m", "streamlit", "run", "main.py", "--server.headless", "true",
         "--server.port", str(PORT), "--browser.gatherUsageStats", "false"],
        cwd=PROJECT_DIR, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    sampler = RssSampler(psutil.Process(server.pid))
    sampler.thread.start()
    results = {}
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page(viewport={"width": 1280, "height": 2400})  # tall: Streamlit scrolls inside the page
            for _ in range(60):
                try:
                    page.goto(f"http://localhost:{PORT}/rag", wait_until="domcontentloaded")
                    break
                except Exception:  # server still starting
                    time.sleep(1)
            page.wait_for_timeout(WARMUP_S * 1000)
            results["chat_page_after_warmup_mb"] = sampler.mark()

            page.goto(f"http://localhost:{PORT}/visit_prep", wait_until="domcontentloaded")
            page.get_by_label("상담 내용").fill(CONSULTATION)
            page.get_by_label("근처 동물병원을 찾을 지역 (선택)").fill("강남구")
            page.wait_for_timeout(1000)
            started = time.perf_counter()
            page.get_by_role("button", name="방문 준비 보고서 만들기").click()
            page.get_by_text("보고서 내려받기").wait_for(timeout=300_000)
            results["team_run_s"] = round(time.perf_counter() - started)
            results["peak_during_team_run_mb"] = sampler.mark()
            page.wait_for_timeout(10_000)
            results["after_run_mb"] = round(sampler.rss() / 2**20)
            page.screenshot(path=str(PROJECT_DIR / "output" / "visit_prep_page.png"), full_page=True)
            browser.close()
    finally:
        sampler.stop.set()
        server.terminate()
    print(json.dumps(results, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
