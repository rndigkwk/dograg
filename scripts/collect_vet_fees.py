"""Collect the regional animal-clinic fee statistics shown on animalclinicfee.or.kr.

    uv run python scripts/collect_vet_fees.py            # collect (resumes), then build the CSVs
    uv run python scripts/collect_vet_fees.py --build    # only rebuild the CSVs from saved responses

The public page (https://animalclinicfee.or.kr/info/payInfo.do) is the government disclosure of
veterinary fees under the Veterinarians Act: for 20 fee items (by weight or species where the
survey splits them) the mean, median, minimum and maximum per si/gun/gu, per si/do and nationally.
It is aggregated survey data, not any hospital's price list.

The page loads its numbers from two JSON endpoints, called here exactly as the page does:
- /info/searchTotalPrice.json (item)          -> national and si/do statistics
- /info/searchPrice.json (si/do, item)        -> every si/gun/gu of that si/do
35 item variants x (1 + 17 si/do) = 630 requests, one at a time, 2 seconds apart. Each response is
saved under data/vet_fees/raw/ and never requested again, so a rerun only fetches what is missing.
No terms of use, licence or robots.txt were found on the site (checked 2026-10-10); the data is
kept out of the public repository like the other collected data until its terms are confirmed.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

PROJECT_DIR = Path(__file__).resolve().parents[1]
BASE = "https://animalclinicfee.or.kr"
PAGE = f"{BASE}/info/payInfo.do"
OUT = PROJECT_DIR / "data" / "vet_fees"
RAW = OUT / "raw"
DELAY_SECONDS = 2.0
HEADERS = {
    "User-Agent": "RagDog portfolio data collection (github.com/rndigkwk/dograg)",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": PAGE,
}


def page_options(html: str) -> tuple[list[dict], list[dict]]:
    """The si/do list and the item variants, read from the page's own controls."""
    select = html[html.find('id="sido1"'):]
    select = select[:select.find("</select>")]
    regions = [{"code": code, "name": name.strip()}
               for code, name in re.findall(r'<option id="searchRegion_\d+" value="(\d+)"[^>]*>([^<]+)</option>', select)]
    items, seen = [], set()
    for tag in re.findall(r'<input[^>]*type="radio"[^>]*>', html):
        attr = dict(re.findall(r'(data-[a-z-]+)="([^"]*)"', tag))
        key = (attr.get("data-medi-type", ""), attr.get("data-animal-type", ""))
        if key[0] and key not in seen:
            seen.add(key)
            items.append({"medi_type_cd": key[0], "animal_type_cd": key[1], "category": attr.get("data-category", ""),
                          "item": attr.get("data-title", ""), "detail": attr.get("data-detail", "")})
    return regions, items


def fetch(session: requests.Session, endpoint: str, data: dict, path: Path) -> list:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    response = session.post(f"{BASE}{endpoint}", data=data, headers=HEADERS, timeout=30)
    response.raise_for_status()
    payload = response.json()
    path.write_text(json.dumps({"collected_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                "request": data, "rows": payload}, ensure_ascii=False), encoding="utf-8")
    time.sleep(DELAY_SECONDS)
    return json.loads(path.read_text(encoding="utf-8"))


def collect() -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    html = session.get(PAGE, headers={"User-Agent": HEADERS["User-Agent"]}, timeout=30).text
    regions, items = page_options(html)
    assert len(regions) == 17 and len(items) >= 30, (len(regions), len(items))
    (OUT / "options.json").write_text(json.dumps({"regions": regions, "items": items}, ensure_ascii=False, indent=1),
                                      encoding="utf-8")
    jobs = [("/info/searchTotalPrice.json", {"mediTypeCd": i["medi_type_cd"], "animalTypeCd": i["animal_type_cd"]},
             RAW / f"total_{i['medi_type_cd']}_{i['animal_type_cd'] or 'all'}.json") for i in items]
    jobs += [("/info/searchPrice.json", {"sidoCd": r["code"], "mediTypeCd": i["medi_type_cd"], "animalTypeCd": i["animal_type_cd"]},
              RAW / f"sido{r['code']}_{i['medi_type_cd']}_{i['animal_type_cd'] or 'all'}.json")
             for r in regions for i in items]
    todo = [job for job in jobs if not job[2].exists()]
    print(f"{len(jobs)} requests, {len(todo)} to fetch (~{len(todo) * DELAY_SECONDS / 60:.0f} min)", flush=True)
    for n, (endpoint, data, path) in enumerate(todo, start=1):
        fetch(session, endpoint, data, path)
        if n % 50 == 0:
            print(f"{n}/{len(todo)}", flush=True)


def build() -> None:
    options = json.loads((OUT / "options.json").read_text(encoding="utf-8"))
    by_key = {(i["medi_type_cd"], i["animal_type_cd"]): i for i in options["items"]}
    fields = ["level", "sido_cd", "sido", "sigungu", "category", "item", "detail", "medi_type_cd", "animal_type_cd",
              "mean", "median", "min", "max", "collected_utc", "source"]
    rows = []
    for path in sorted(RAW.glob("*.json")):
        saved = json.loads(path.read_text(encoding="utf-8"))
        request = saved["request"]
        item = by_key[(request["mediTypeCd"], request["animalTypeCd"])]
        for row in saved["rows"]:
            # searchTotalPrice: one row per si/do plus the nation (SIDO_CD 99); searchPrice: si/gun/gu rows.
            if "sidoCd" in request:
                level, sido_cd, sido = "sigungu", row.get("ADDR1_CD") or row.get("SIDO_CD"), row.get("ADDR1_NM")
            elif row.get("SIDO_CD") == "99":
                level, sido_cd, sido = "national", "99", "전국"
            else:
                level, sido_cd, sido = "sido", row.get("SIDO_CD"), row.get("SIDO_NM")
            rows.append({
                "level": level, "sido_cd": sido_cd or "", "sido": sido or "",
                "sigungu": (row.get("ADDR2_NM") or "") if level == "sigungu" else "",
                "category": item["category"], "item": item["item"], "detail": item["detail"],
                "medi_type_cd": request["mediTypeCd"], "animal_type_cd": request["animalTypeCd"],
                "mean": row.get("AVG_PRICE"), "median": row.get("MID_PRICE"), "min": row.get("MIN_PRICE"),
                "max": row.get("MAX_PRICE"), "collected_utc": saved["collected_utc"], "source": PAGE,
            })
    with open(OUT / "vet_fees.csv", "w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    levels = {level: sum(r["level"] == level for r in rows) for level in ("national", "sido", "sigungu")}
    print(f"{len(rows)} rows -> {OUT / 'vet_fees.csv'}: {levels}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--build", action="store_true")
    args = parser.parse_args()
    if not args.build:
        collect()
    build()
    return 0


if __name__ == "__main__":
    sys.exit(main())
