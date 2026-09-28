# DogRAG Health Quality and Safety Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Audit health Q&A quality, compare an inexpensive retrieval reranker with the current baseline, and prevent unsupported or unsafe health answers.

**Architecture:** Keep the original CSV and Chroma collection unchanged. Put audit and reranking logic in pure modules, run offline evaluation on a disposable Chroma copy, and connect the chosen search method and safety decisions to `pages/rag.py`.

**Tech Stack:** Python 3.12, pandas, scikit-learn (already installed), LangChain Chroma, Streamlit 1.61, unittest.

**Spec:** `docs/superpowers/specs/2026-09-27-dograg-quality-safety-location-citations-design.md`

## Global Constraints

- Do not overwrite `data/df.csv`, `data/df_val.csv`, or `data/chroma_db/`; all vector queries for tests and evaluation use a disposable copy.
- Never infer a new disease diagnosis for a row labeled `기타`; retain raw labels alongside any derived normalization.
- Benchmark baseline and candidate on the same fixed validation rows; report overall and `기타`/non-`기타` `hit@3`, `MRR@3`, and misses. Do not call these clinical accuracy.
- Enable the candidate search by default only if overall `hit@3` improves and non-`기타` `hit@3` does not worsen; otherwise keep the baseline and report the result.
- Preserve all pre-existing dirty files and hunks. Stage/commit only reviewed task changes; skip a task commit if an overlapping pre-existing hunk cannot be separated safely.
- The only approved external model calls are the minimal health and report smoke calls after local work; inspect retrieved text for personal information before sending it, and never print secrets or raw passages.

## Review Focus

- A validation label may be missing: the audit must count it without inventing a replacement (Task 1 test).
- `기타` dominates validation: subgroup metrics must be emitted even if one subgroup is empty (Task 2 test).
- The reranker may receive empty text or duplicate candidates: ordering must stay deterministic (Task 2 test).
- A question can mention an emergency in the negative, e.g. `호흡곤란은 없어요`: avoid a false emergency flag (Task 3 test).
- Chroma may return no documents: do not invoke the LLM and clearly state insufficient evidence (Task 3 test).

---

### Task 1: Reproducible health-data audit

**Files:** Create `src/health_quality.py`, `tests/test_health_quality.py`, `scripts/audit_health_data.py`; update `README.md` data counts with measured values.

**Interfaces:** Produce `audit_health_data(train: pandas.DataFrame, validation: pandas.DataFrame) -> dict` and `normalize_label(value: object) -> str | None`. The CLI reads the two repository CSVs and writes `output/health_data_audit.json` without changing source files.

- [ ] **Step 1: Write failing tests.** `test_audit_counts_missing_duplicates_and_other` uses a hand-written three-row fixture and asserts exact missing/duplicate/`기타` counts; `test_normalize_label_keeps_original_diagnosis` asserts whitespace normalization but no disease reassignment.
- [ ] **Step 2: Verify red.** Run `.venv\Scripts\python.exe -m unittest discover -s tests -p test_health_quality.py -v`; expect failures caused by absent audit functions.
- [ ] **Step 3: Implement the audit.** Add the two functions and a CLI `main() -> int` that reports row counts, required-column failures, nulls, duplicates, raw/normalized label distributions, and train/validation question overlap.
- [ ] **Step 4: Verify green and real data.** Run the targeted test, then `.venv\Scripts\python.exe scripts\audit_health_data.py`; expect 19,206 training rows, 561 validation rows, and 14,774 raw `기타` rows; inspect the JSON output.
- [ ] **Step 5: Commit only isolated audit changes.** If `README.md` contains earlier dirty hunks, keep them intact and stage only this task's hunk.

### Task 2: Candidate reranker and fair offline comparison

**Files:** Create `src/health_retrieval.py`, `tests/test_health_retrieval.py`, `tests/evaluate_health_retrieval.py`; modify `tests/chroma_smoke.py` only if needed to share disposable-copy behavior; modify `pages/rag.py:198-222` only after benchmark passes the activation gate.

**Interfaces:** Produce `rerank_candidates(question: str, docs: list, top_k: int) -> list` using character n-gram overlap with stable original-rank ties. The evaluator returns baseline/candidate dictionaries with overall and subgroup `hit@3`, `mrr@3`, and misses, and saves `output/health_retrieval_comparison.json`.

- [ ] **Step 1: Write failing tests.** Test that a hand-labeled symptom document moves above an unrelated one, duplicate/empty text is stable, and subgroup summaries report literal expected rates for `기타`, non-`기타`, and an empty subgroup.
- [ ] **Step 2: Verify red.** Run `.venv\Scripts\python.exe -m unittest discover -s tests -p test_health_retrieval.py -v`; expect behavior assertions to fail before implementation.
- [ ] **Step 3: Implement pure ranking and metrics.** Search a larger vector candidate pool (12) and rerank to the requested top-k; preserve Chroma order on lexical ties. Compare with baseline top-3 on the same 561 validation rows using the notebook's three-key metadata relevance definition.
- [ ] **Step 4: Verify green and benchmark.** Run targeted tests and `.venv\Scripts\python.exe tests\evaluate_health_retrieval.py`; confirm the original Chroma files remain unchanged. Record baseline/candidate metrics and activate reranking in `ask_rag()` only if the global gate passes. If it fails, retain baseline and document why.
- [ ] **Step 5: Commit only isolated ranking/evaluation changes.** Do not stage unrelated existing edits in `pages/rag.py`.

### Task 3: Evidence refusal and conservative urgent-care notice

**Files:** Create `src/health_safety.py`, `tests/test_health_safety.py`; modify `pages/rag.py:198-222`, `pages/rag.py:788-941`; extend `tests/test_regressions.py` for route/UI behavior.

**Interfaces:** Produce `detect_urgent_sign(question: str) -> str | None` and `has_usable_evidence(scored_docs: list[tuple], threshold: float | None) -> bool`. `ask_rag()` returns `answer`, `evidence_rows`, and `safety_notice`; `chatbot()` propagates the notice to the UI.

- [ ] **Step 1: Write failing tests.** Assert clear urgent examples (`숨을 못 쉬어요`, `계속 헛구역질만 해요`, toxic ingestion) show veterinary-care language; plain `구토` and negated `호흡곤란은 없어요` do not. Assert an empty retrieval result yields an insufficient-evidence answer and the fake LLM is never invoked.
- [ ] **Step 2: Verify red.** Run `.venv\Scripts\python.exe -m unittest discover -s tests -p test_health_safety.py -v`; expect behavior failures against current code.
- [ ] **Step 3: Implement guards.** Use only source-backed urgent patterns; keep the notice separate from model text. Inspect similarity-score semantics and calibrate against held-out in-domain/irrelevant queries before setting any threshold. If calibration is unreliable, ship only the empty-result guard and document the limitation.
- [ ] **Step 4: Verify green and UI.** Run targeted and full unittest suites. With `AppTest`, submit an urgent health question using a fake retriever/model and assert the warning is visible without treating it as a diagnosis.
- [ ] **Step 5: Commit only isolated safety changes.** Preserve pre-existing routing modifications in `pages/rag.py`.

### Task 4: Health-path integration check

**Files:** Update `README.md` health/search/limitations text and `tests/chroma_smoke.py` if its output needs a health-path assertion.

**Interfaces:** No new public interface. Consumes Tasks 1-3.

- [ ] **Step 1: Run the complete local suite.** `.venv\Scripts\python.exe -m unittest discover -s tests -v` and `.venv\Scripts\python.exe tests\chroma_smoke.py` must exit 0.
- [ ] **Step 2: Inspect output and source state.** Report the audit/benchmark numbers, candidate activation decision, calibration outcome, and `git status --short`; original data files must not be modified.
- [ ] **Step 3: Update README and commit only isolated documentation changes.** State the measured counts and that matching metadata is not clinical accuracy.
