# DogRAG Nearest Hospital Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace misleading `LIMIT 1` proximity answers with opt-in, straight-line-distance-ranked hospitals while retaining regional search when location is unavailable.

**Architecture:** A pure geospatial module converts stored EPSG:5174 coordinates to WGS84 and ranks valid rows by Haversine distance. A trusted Streamlit v2 component requests browser location only on a button click, and both the hospital page and chat route consume the same ranking function.

**Tech Stack:** Python 3.12, SQLite, pyproj, Streamlit 1.61 `st.components.v2`, browser Geolocation API, unittest/AppTest.

**Spec:** `docs/superpowers/specs/2026-09-27-dograg-quality-safety-location-citations-design.md`

## Global Constraints

- Do not deploy the app or request this computer's real location for tests. Use fixed mock coordinates; actual permission behavior on hosted HTTPS remains a reported deployment check.
- Location is opt-in and ephemeral: never write it to SQLite, files, logs, or chat history. Denial, timeout, insecure-context, and unsupported-browser cases leave region search available.
- Label distances as straight-line kilometers, never road distance, travel time, or verified hospital operating status.
- Keep existing region/count/single-hospital behavior except the incorrect nearest-`LIMIT 1` path. Query source SQLite in read-only mode for proximity ranking.
- Preserve pre-existing dirty files and hunks; stage/commit only separable task changes.

## Review Focus

- Latitude and longitude can be swapped or outside valid ranges: reject them, not rank nonsense (Task 1 test).
- Hospital coordinates can be null, nonnumeric, or outside Korea: exclude them while retaining valid rows (Task 1 test).
- Identical distances need stable ordering by ID so maps and tables do not jump (Task 1 test).
- A browser can deny or time out after the user clicks: show a clear message and keep the two region selectors usable (Task 2 test).
- A user can ask “nearest hospital” without location: do not claim the first DB row is nearest (Task 3 test).

---

### Task 1: Validated geospatial ranking

**Files:** Create `src/hospital_distance.py`, `tests/test_hospital_distance.py`.

**Interfaces:** Produce `nearest_hospitals(rows: list[dict], latitude: float, longitude: float, limit: int = 10) -> list[dict]`; each output row adds `latitude`, `longitude`, and `distance_km`, preserving the source hospital fields. Raise `ValueError` for invalid user coordinates.

- [ ] **Step 1: Write failing tests.** Use two manually chosen hospital coordinates with hand-checked distance ordering; assert 0 km at the same coordinate, increasing `distance_km`, stable ID tie order, and exclusion of null/out-of-range hospital coordinates. Assert invalid user coordinates raise `ValueError`.
- [ ] **Step 2: Verify red.** Run `.venv\Scripts\python.exe -m unittest discover -s tests -p test_hospital_distance.py -v`; expect missing behavior failures.
- [ ] **Step 3: Implement distance calculation.** Convert EPSG:5174 with `Transformer.from_crs(..., always_xy=True)`, validate WGS84 coordinates, calculate Haversine kilometers, sort `(distance_km, ids)`, cap to `limit`.
- [ ] **Step 4: Verify green and actual DB shape.** Run targeted tests and a read-only 5,448-row query through the function using fixed Seoul coordinates; assert results are sorted and include names/addresses.
- [ ] **Step 5: Commit the isolated module/tests.** Do not include `data/hospital.db` or unrelated code.

### Task 2: Opt-in location control and hospital-page fallback

**Files:** Create `src/location_component.py`, `tests/test_location_component.py`; modify `pages/hospital.py:1-100,205-396` and add `tests/test_hospital_page.py`.

**Interfaces:** Produce `render_location_control(key: str) -> tuple[tuple[float, float] | None, str | None]`. Status string represents denied/timeout/unsupported/insecure errors; a successful coordinate is validated by Task 1 before use.

- [ ] **Step 1: Write failing tests.** With a fake component result, assert no location is requested on initial page render; a valid mock coordinate produces a nearest-hospital table/map and a straight-line-distance label; denied/timeout/unsupported/insecure results show a message while both region selectors and the region-search button remain.
- [ ] **Step 2: Verify red.** Run `.venv\Scripts\python.exe -m unittest discover -s tests -p test_hospital_page.py -v` and the component test; expect the missing control and distance display assertions to fail.
- [ ] **Step 3: Implement the component and page.** Register `st.components.v2.component` once with trusted static HTML/JS; JS calls `navigator.geolocation.getCurrentPosition()` only in the button handler, sends coordinates/status to Python, and cleans up click handlers. Region search remains independent of component state; avoid persisting coordinates outside the Streamlit session.
- [ ] **Step 4: Verify green.** Run targeted tests and a real `AppTest` page render. If AppTest cannot execute component JS, test Python state handling and inspect the button in a browser with mocked geolocation; explicitly report any unverified real permission flow.
- [ ] **Step 5: Commit isolated UI/component changes.** Do not stage unrelated files.

### Task 3: Deterministic nearest-hospital chat path

**Files:** Modify `pages/rag.py:467-604,788-941`, `tests/test_regressions.py`; add `tests/test_nearest_hospital_chat.py`.

**Interfaces:** Extend `run_sql_search(question: str, location: tuple[float, float] | None = None) -> tuple[str, list[dict]]` and `chatbot(..., location: tuple[float, float] | None = None) -> dict`. Proximity questions with a location bypass LLM SQL and use Task 1 ranking on a read-only DB query.

- [ ] **Step 1: Write failing tests.** With two fixture hospitals, assert the nearer one wins even if inserted second; without location, assert a guidance answer and no “nearest” claim; the chat page exposes the opt-in location control; ordinary district count and `하나만` queries retain existing results.
- [ ] **Step 2: Verify red.** Run `.venv\Scripts\python.exe -m unittest discover -s tests -p test_nearest_hospital_chat.py -v`; expect nearest ordering/absence behavior failures.
- [ ] **Step 3: Implement deterministic branch.** Mount the Task 2 location control on `pages/rag.py` as well as the hospital page, then pass its ephemeral coordinate to `chatbot()` and `run_sql_search()`; query only required hospital columns in SQLite read-only mode and format distance in km. Keep normal SQL validation and non-nearest paths unchanged.
- [ ] **Step 4: Verify green and regression.** Run targeted tests, `tests/test_regressions.py`, and the full suite; verify location is absent from messages, database writes, and logs.
- [ ] **Step 5: Commit only separable chat changes.** Preserve earlier uncommitted routing hunks in `pages/rag.py`.

### Task 4: Document and check location boundaries

**Files:** Modify `README.md` hospital and limitations sections.

**Interfaces:** No new public interface. Consumes Tasks 1-3.

- [ ] **Step 1: Update README.** Document opt-in HTTPS permission, denial fallback, straight-line distance, and the lack of road/operating-status data.
- [ ] **Step 2: Run `.venv\Scripts\python.exe -m unittest discover -s tests -v` and `git diff --check`.** Confirm no hospital DB modification in `git status --short`.
- [ ] **Step 3: Commit only isolated documentation changes.** Keep prior README edits intact.
