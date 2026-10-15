"""The numbers behind the data page (app_pages/data.py) and GET /stats (api/stats.py, ADR-0008).

Counts only, never consultation text: the ten most asked-about diseases (without "기타"), the
consultations per department, the animal hospitals per province, and how each public source
became the place database. The queries are the page's own, moved here unchanged. They are
computed once per process (the data changes only with a new deployment).
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from functools import lru_cache

import pandas as pd

from src import resources, settings
from src.data_charts import normalize_province
from src.places_data import KIND_LABELS

CONSULTATIONS = settings.PROJECT_DIR / "data" / "df.csv"
REQUIRED_COLUMNS = {"meta.disease", "meta.department"}


class StatsUnavailable(RuntimeError):
    """The consultation file is missing, empty or lacks its columns."""


@lru_cache(maxsize=1)
def _consultations() -> pd.DataFrame:
    if not CONSULTATIONS.exists() or CONSULTATIONS.stat().st_size <= 2:
        raise StatsUnavailable(f"그래프 데이터 파일이 비어 있습니다: {CONSULTATIONS}")
    try:
        frame = pd.read_csv(CONSULTATIONS, usecols=lambda column: column in REQUIRED_COLUMNS)
    except pd.errors.EmptyDataError as error:
        raise StatsUnavailable(f"그래프 데이터 파일을 읽을 수 없습니다: {CONSULTATIONS}") from error
    if missing := REQUIRED_COLUMNS.difference(frame.columns):
        raise StatsUnavailable(f"데이터에 필요한 컬럼이 없습니다: {', '.join(sorted(missing))}")
    return frame


def _places(database: str, sql: str) -> pd.DataFrame:
    with closing(sqlite3.connect(f"file:{database}?mode=ro", uri=True)) as connection:
        return pd.read_sql_query(sql, connection)


@lru_cache(maxsize=1)
def disease_counts(top: int = 10) -> pd.Series:
    frame = _consultations()
    return frame.loc[frame["meta.disease"] != "기타", "meta.disease"].value_counts().head(top)


@lru_cache(maxsize=1)
def department_counts() -> pd.Series:
    return _consultations()["meta.department"].astype("string").str.strip().fillna("결측").value_counts()


def hospitals_by_province() -> pd.Series:
    return _hospitals_by_province(resources.DB_PATH.as_posix())


@lru_cache(maxsize=2)  # keyed by the database file, so a test database is not served the real counts
def _hospitals_by_province(database: str) -> pd.Series:
    hospitals = _places(database, "SELECT road_address, lot_address FROM place WHERE kind = 'hospital'")
    return (hospitals["road_address"].fillna(hospitals["lot_address"]).map(normalize_province)
            .value_counts().sort_values(ascending=False))


def place_sources() -> list[dict]:
    """Each public source in the page's kind order, with its cleaning steps as a list."""
    return [dict(row) for row in _place_sources(resources.DB_PATH.as_posix())]


@lru_cache(maxsize=2)
def _place_sources(database: str) -> tuple[dict, ...]:
    sources = _places(database, "SELECT * FROM source").to_dict("records")
    order = list(KIND_LABELS)
    for row in sources:
        row["label"] = KIND_LABELS[row["kind"]]
        row["notes"] = json.loads(row["notes"] or "[]")
    return tuple(sorted(sources, key=lambda row: order.index(row["kind"])))
