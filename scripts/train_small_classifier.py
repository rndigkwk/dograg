"""A small classifier in place of the two Decisions calls: the app's embedding + logistic regression.

    uv run --group tools python scripts/train_small_classifier.py     # no model calls

The app calls OpenAI Decisions (about 0.3 s) when its rules decide nothing: the route of a question
(src/tools/router.py, 15% of the routing questions) and whether it is an emergency
(src/tools/urgency.py). This trains two logistic regressions on the embedding the app already has
in memory (ko-sroberta-dograg-b, ONNX int8, src/resources.load_health_embeddings) over synthetic
questions (data/classifier/train.jsonl, scripts/make_classifier_data.py), so a fallback would add
no model file and no API call. It is measured the way the Decisions fallbacks were:
- route: the 136 routing questions of scripts/evaluate_router_speed.py; the rules decide first and
  the classifier only where they give up (as Decisions does); the Decisions numbers are from
  docs/wiki/router.md (134/136, 19 of the 20 fallback questions).
- urgency: tests/data/emergency_signs.json holdout and holdout2 (urgent caught, false alarms) and
  the extra-warning rate on the 200 guardian questions the rules miss (random.Random(7), as
  scripts/evaluate_emergency.py); Decisions: 19/20 0/20, 19/20 0/20, 9%.
Results: output/experiments/small_classifier.json.
"""

from __future__ import annotations

import json
import os
import random
import sys
import time
from pathlib import Path

import numpy as np

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))
sys.path.insert(0, str(PROJECT_DIR / "scripts"))

TRAIN = PROJECT_DIR / "data" / "classifier" / "train.jsonl"
OUT = PROJECT_DIR / "output" / "experiments" / "small_classifier.json"
FALLBACK = "__fallback__"
DECISIONS = {"route_all": "134/136", "route_fallback": "19/20", "holdout": "19/20, 0/20", "holdout2": "19/20, 0/20",
             "extra_warning_rate": 0.09}


def embed(embedder, texts: list[str]) -> np.ndarray:
    vectors = []
    for start in range(0, len(texts), 64):
        vectors += embedder.embed_documents(texts[start:start + 64])
    return np.asarray(vectors, dtype=np.float32)


def rule_route(question: str) -> str:
    """The app's route with the rules only: FALLBACK where the app would ask Decisions."""
    from unittest.mock import patch

    from src.tools import router

    with patch("src.resources.load_chat_model", return_value=object()), \
            patch.object(router, "decide_route", return_value=FALLBACK):
        return router.classify_question(question)


def main() -> int:
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    import evaluate_emergency
    import evaluate_router_speed
    from sklearn.linear_model import LogisticRegression

    from src import resources
    from src.health_safety import detect_urgent_sign
    from src.tools.urgency import needs_second_check

    rows = [json.loads(line) for line in TRAIN.read_text(encoding="utf-8").splitlines() if line.strip()]
    embedder = resources.load_health_embeddings()
    report = {"train": {}, "decisions": DECISIONS}
    models = {}
    for task in ("route", "urgency"):
        texts = [row["text"] for row in rows if row["task"] == task]
        labels = [row["label"] for row in rows if row["task"] == task]
        model = LogisticRegression(max_iter=2000, class_weight="balanced", C=4.0)
        model.fit(embed(embedder, texts), labels)
        models[task] = model
        report["train"][task] = {label: labels.count(label) for label in sorted(set(labels))}

    # --- route: rules first, the classifier where they give up
    questions = evaluate_router_speed.questions()
    vectors = embed(embedder, [q["question"] for q in questions])
    predicted = models["route"].predict(vectors)
    rows_out, fallback_ok, fallback_n, alone_ok, combined_ok = [], 0, 0, 0, 0
    for q, guess in zip(questions, predicted):
        rule = rule_route(q["question"])
        final = guess if rule == FALLBACK else rule
        alone_ok += guess == q["expected"]
        combined_ok += final == q["expected"]
        if rule == FALLBACK:
            fallback_n += 1
            fallback_ok += guess == q["expected"]
        rows_out.append({"id": q["id"], "expected": q["expected"], "rule": rule, "classifier": guess, "final": final})
    report["route"] = {"questions": len(questions), "rules_plus_classifier": combined_ok, "classifier_alone": alone_ok,
                       "fallback": f"{fallback_ok}/{fallback_n}",
                       "fallback_misses": [r for r in rows_out if r["rule"] == FALLBACK and r["final"] != r["expected"]]}
    if "--decisions" in sys.argv:
        # The same fallback questions through the app's Decisions call (one call each), for a fair comparison.
        from cost_guard import confirm

        from src.tools import router

        fallback_rows = [(q, r) for q, r in zip(questions, rows_out) if r["rule"] == FALLBACK]
        if confirm("train_small_classifier --decisions", len(fallback_rows), "one Decisions call per fallback question"):
            got = [(router.decide_route(q["question"]), q["expected"]) for q, _ in fallback_rows]
            report["route"]["decisions_fallback"] = f"{sum(route == expected for route, expected in got)}/{len(got)}"
            report["route"]["decisions_misses"] = [{"id": q["id"], "expected": q["expected"], "decisions": route}
                                                   for (q, _), (route, _) in zip(fallback_rows, got) if route != q["expected"]]

    # --- urgency: the rules first, the classifier where they find nothing (as urgent_notice does)
    def classifier_urgent(texts: list[str]) -> list[bool]:
        return [label == "emergency_now" for label in models["urgency"].predict(embed(embedder, texts))]

    items = json.loads((PROJECT_DIR / "tests" / "data" / "emergency_signs.json").read_text(encoding="utf-8"))["items"]
    second = [item for item in items if not detect_urgent_sign(item["question"]) and needs_second_check(item["question"])]
    second_flags = dict(zip([item["id"] for item in second], classifier_urgent([item["question"] for item in second])))
    for item in items:
        item["flagged"] = bool(detect_urgent_sign(item["question"])) or second_flags.get(item["id"], False)
    report["urgency"] = {split: evaluate_emergency.score([i for i in items if i["split"] == split])
                         for split in ("dev", "holdout", "holdout2")}
    corpus = evaluate_emergency.corpus_questions()
    unflagged = [question for question in corpus if not detect_urgent_sign(question)]
    sample = random.Random(7).sample(unflagged, 200)
    flags = classifier_urgent(sample)
    report["urgency"]["corpus_extra_warning_rate"] = round(sum(flags) / len(sample), 3)
    report["urgency"]["corpus_examples"] = [q[:160] for q, flag in zip(sample, flags) if flag][:12]

    # A stricter emergency threshold, chosen on dev only (no false alarm there), then read on the rest.
    emergency = list(models["urgency"].classes_).index("emergency_now")
    second_p = dict(zip([item["id"] for item in second],
                        models["urgency"].predict_proba(embed(embedder, [item["question"] for item in second]))[:, emergency]))
    sample_p = models["urgency"].predict_proba(embed(embedder, sample))[:, emergency]

    def at(threshold: float) -> dict:
        for item in items:
            item["flagged"] = bool(detect_urgent_sign(item["question"])) or second_p.get(item["id"], 0.0) >= threshold
        scores = {split: evaluate_emergency.score([i for i in items if i["split"] == split]) for split in ("dev", "holdout", "holdout2")}
        return {"threshold": threshold, **{split: f"{s['caught']}/{s['urgent']}, {s['false_alarms']}/{s['non_urgent']}"
                                           for split, s in scores.items()},
                "dev_false_alarms": scores["dev"]["false_alarms"], "dev_caught": scores["dev"]["caught"],
                "corpus_rate": round(float((sample_p >= threshold).mean()), 3)}

    sweep = [at(threshold) for threshold in (0.5, 0.6, 0.7, 0.8, 0.9, 0.95)]
    clean = [row for row in sweep if row["dev_false_alarms"] == 0]
    report["urgency"]["threshold_sweep"] = sweep
    report["urgency"]["chosen_on_dev"] = max(clean, key=lambda row: row["dev_caught"]) if clean else None

    # --- latency: one question, embedding + both predictions (the app embeds the question anyway)
    started = time.perf_counter()
    for q in questions[:50]:
        vector = embed(embedder, [q["question"]])
        models["route"].predict(vector), models["urgency"].predict(vector)
    report["latency_ms_per_question"] = round((time.perf_counter() - started) * 1000 / 50, 1)

    print(json.dumps({k: v for k, v in report.items() if k != "route"} | {"route": {k: v for k, v in report["route"].items()
                     if k != "fallback_misses"}}, ensure_ascii=False, indent=1))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
