"""Personal data masking on tests/data/pii_cases.json (rules only, no model calls).

    uv run python scripts/evaluate_pii.py

mask cases pass when the string is gone after src/pii.mask_pii; keep cases when it is still there.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))


def main() -> int:
    from src.pii import mask_pii

    sys.stdout.reconfigure(encoding="utf-8")
    items = json.loads((PROJECT_DIR / "tests" / "data" / "pii_cases.json").read_text(encoding="utf-8"))["items"]
    totals: dict[tuple[str, str], list[int]] = {}
    for item in items:
        masked = mask_pii(item["text"])
        for kind in ("mask", "keep"):
            if kind not in item:
                continue
            ok = (item[kind] not in masked) if kind == "mask" else (item[kind] in masked)
            totals.setdefault((item["split"], kind), [0, 0])
            totals[(item["split"], kind)][0] += ok
            totals[(item["split"], kind)][1] += 1
            if not ok:
                print(f"  {item['id']} {kind} {item[kind]!r}: {masked}")
    for (split, kind), (ok, n) in sorted(totals.items()):
        print(f"{split:8} {kind}: {ok}/{n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
