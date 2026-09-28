"""Write a non-mutating audit of the two health Q&A files."""

import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.health_quality import audit_health_data


def main() -> int:
    result = audit_health_data(pd.read_csv(ROOT / "data" / "df.csv"), pd.read_csv(ROOT / "data" / "df_val.csv"))
    target = ROOT / "output" / "health_data_audit.json"
    target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"train={result['train']['rows']} validation={result['validation']['rows']} overlap={result['question_overlap']} output={target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
