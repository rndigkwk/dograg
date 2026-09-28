# DogRAG Report Evidence and Final Verification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every report answer inspectable through retrieved excerpts and the correct PDF page, then verify all four requested improvements with local tests and minimal live model calls.

**Architecture:** Keep the existing string-returning tool API while adding a structured report-analysis function for `chatbot()`. A small PDF helper renders a validated 1-based source page; the Streamlit UI presents excerpts and page previews without using the stale absolute source path in Chroma metadata.

**Tech Stack:** Python 3.12, LangChain Chroma, PyMuPDF, Streamlit 1.61, unittest/AppTest, configured OpenAI API.

**Spec:** `docs/superpowers/specs/2026-09-27-dograg-quality-safety-location-citations-design.md`

## Global Constraints

- Never change the source PDF, source CSV, or original Chroma DB during tests; use the existing disposable Chroma-copy smoke pattern.
- Chroma report `page` is 1-based. The repository PDF is `data/2025 한국 반려동물 보고서.pdf`; never expose the obsolete absolute `source_path` as a link.
- Preserve `report_analysis_tool(question) -> str` for callers while returning structured evidence to `chatbot()` and the UI.
- Preserve pre-existing dirty files and hunks; stage/commit only separable task changes.
- After all three plans pass locally, invoke the real model with one synthetic health and one synthetic report question if permitted. Review retrieved passages locally for obvious personal data first; never print API keys or full passages. If policy or network blocks a call, do not route around the block.

## Review Focus

- Report results may have no retrieved documents: the answer must say evidence is insufficient and show no bogus page (Task 1 test).
- Multiple chunks can share one PDF page: excerpts remain associated with their own chunk, and preview work is cached/deduplicated per page (Task 2 test).
- Metadata page can be null, zero, nonnumeric, or past the document end: show text evidence without crashing (Task 2 test).
- The PDF file can be missing or unreadable: show a short explanation instead of an app exception (Task 2 test).
- The external model can be unavailable: retain evidence and give a bounded failure message rather than silently implying a verified analysis (Task 3 test).

---

### Task 1: Structured report result with a compatible tool wrapper

**Files:** Create `src/report_evidence.py`, `tests/test_report_evidence.py`; modify `pages/rag.py:336-362,788-826`.

**Interfaces:** Produce `report_evidence_from_docs(docs: list) -> list[dict]` with `page: int | None`, `excerpt: str`, and `source: str` (basename only). Add `analyze_report(question: str) -> dict` returning `answer` and `evidence_rows`; keep `run_report_analysis(question: str) -> str` and `report_analysis_tool(question: str) -> str` as text wrappers. `chatbot()` consumes `analyze_report()` for the analysis route.

- [ ] **Step 1: Write failing tests.** With fake Chroma docs and a fake model, assert a 1-based page and excerpt reach `chatbot()['evidence_rows']`; malformed page metadata becomes `None`; assert `report_analysis_tool.invoke({"question": question})` still returns only answer text; an empty document list yields an explicit insufficient-evidence answer without model invocation.
- [ ] **Step 2: Verify red.** Run `.venv\Scripts\python.exe -m unittest discover -s tests -p test_report_evidence.py -v`; expect missing structure/empty-result behavior failures.
- [ ] **Step 3: Implement structured analysis.** Normalize only trusted metadata fields, keep the prompt sourced from the same retrieved docs, and avoid leaking full original metadata (including stale `source_path`) to the UI.
- [ ] **Step 4: Verify green.** Run targeted tests plus `tests/test_regressions.py`; verify existing health and SQL route contracts remain.
- [ ] **Step 5: Commit only separable report-data changes.** Do not stage earlier dirty `pages/rag.py` hunks.

### Task 2: Validated PDF page preview in Streamlit

**Files:** Extend `src/report_evidence.py`, `tests/test_report_evidence.py`; modify `pages/rag.py:910-935`; add `tests/test_report_page_ui.py`.

**Interfaces:** Produce `render_pdf_page(pdf_path: Path, page: int) -> bytes | None` as a cached helper; `None` means missing/unreadable/out-of-range. The UI shows each excerpt and renders one preview per valid page.

- [ ] **Step 1: Write failing tests.** Build a temporary two-page PDF with PyMuPDF. Assert page 1 and 2 render nonempty distinct PNG bytes, page 0/page 3/absent PDF return `None`; two chunks on page 2 display both excerpts but render one preview; a fake analysis result displays `페이지 2` in AppTest.
- [ ] **Step 2: Verify red.** Run `.venv\Scripts\python.exe -m unittest discover -s tests -p test_report_evidence.py -v` and `-p test_report_page_ui.py -v`; expect missing rendering/UI behavior failures.
- [ ] **Step 3: Implement preview/UI.** Convert 1-based `page` to PyMuPDF index at the renderer boundary, cache by PDF path/page, show a per-page fallback warning on invalid input, and render only unique page previews to limit CPU/memory.
- [ ] **Step 4: Verify green.** Run targeted and full suites; inspect one real report chunk from a temporary Chroma copy against the repository PDF page count.
- [ ] **Step 5: Commit isolated preview changes.** Keep the original PDF untouched.

### Task 3: Final cross-feature verification and documentation

**Files:** Create `tests/live_model_smoke.py` (manual opt-in CLI, excluded from unittest discovery); modify `README.md` for the four behaviors, limits, data counts, and test commands.

**Interfaces:** The CLI accepts `--allow-external-corpus` before making any API call, then reports only route, evidence count, nonempty-answer status, and failure category. It does not dump prompts, retrieved passages, keys, or full model responses.

- [ ] **Step 1: Write failing smoke-contract tests.** Assert the CLI refuses to call an external model without its explicit flag, redacts response/passages in its output, and classifies a fake connection failure as unverified rather than success; use fake model responses for the automated test.
- [ ] **Step 2: Verify red.** Run `.venv\Scripts\python.exe -m unittest discover -s tests -p test_live_model_smoke.py -v`; expect missing CLI/contract failures.
- [ ] **Step 3: Implement the opt-in CLI and README.** Document synthetic questions, corpus-export warning, local-only tests, and the separately unverified real HTTPS geolocation permission path.
- [ ] **Step 4: Verify all local behavior.** Run `.venv\Scripts\python.exe -m unittest discover -s tests -v`, `.venv\Scripts\python.exe tests\chroma_smoke.py`, `.venv\Scripts\python.exe -m compileall -q main.py pages src tests`, PDF/SVG checks, and `git diff --check`. Compare `git status --short` before/after Chroma tests.
- [ ] **Step 5: Run minimal live model calls.** Inspect the selected retrieved snippets for obvious personal information, then run `.venv\Scripts\python.exe tests\live_model_smoke.py --allow-external-corpus` once. Require one health and one report route with nonempty answers and evidence; if rejected or unavailable, stop and report the exact unverified scope without a workaround.
- [ ] **Step 6: Handoff.** Report baseline/candidate metrics and activation decision, emergency/empty-result tests, nearest-distance sample and privacy behavior, PDF page evidence, live-model outcome, and final Git status. Commit only separable new work; never push/deploy without a separate request.
