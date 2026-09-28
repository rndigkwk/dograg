"""Read-only quality audit for the health Q&A CSVs."""

import pandas as pd


def normalize_label(value: object) -> str | None:
    if pd.isna(value):
        return None
    normalized = " ".join(str(value).split())
    return normalized or None


def _describe(frame: pd.DataFrame) -> dict:
    required = ("meta.lifeCycle", "meta.department", "meta.disease", "qa.input", "qa.output")
    labels = frame["meta.disease"].map(normalize_label) if "meta.disease" in frame else pd.Series(dtype=str)
    departments = frame["meta.department"].map(normalize_label) if "meta.department" in frame else pd.Series(dtype=str)
    questions = frame["qa.input"].dropna().astype(str) if "qa.input" in frame else pd.Series(dtype=str)
    return {
        "rows": len(frame),
        "missing_required_columns": [column for column in required if column not in frame],
        "missing": {column: int(frame[column].isna().sum()) for column in required if column in frame},
        "duplicate_questions": int(questions.duplicated().sum()),
        "raw_labels": {str(key): int(value) for key, value in frame["meta.disease"].value_counts(dropna=False).items()} if "meta.disease" in frame else {},
        "normalized_labels": {str(key): int(value) for key, value in labels.value_counts(dropna=False).items()},
        "raw_departments": {str(key): int(value) for key, value in frame["meta.department"].value_counts(dropna=False).items()} if "meta.department" in frame else {},
        "normalized_departments": {str(key): int(value) for key, value in departments.value_counts(dropna=False).items()},
    }


def audit_health_data(train: pd.DataFrame, validation: pd.DataFrame) -> dict:
    left = set(train["qa.input"].dropna().astype(str)) if "qa.input" in train else set()
    right = set(validation["qa.input"].dropna().astype(str)) if "qa.input" in validation else set()
    return {"train": _describe(train), "validation": _describe(validation), "question_overlap": len(left & right)}
