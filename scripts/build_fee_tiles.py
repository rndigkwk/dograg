"""Where each city or district sits on the fee page's tile map (web/src/lib/feeTiles.json).

    uv run python scripts/build_fee_tiles.py

The fee page draws one province at a time as a grid of equal tiles, one per city or district the
survey covers (data/vet_fees/vet_fees.csv), each placed near where it is. "Where it is" is the median
latitude and longitude of the places in data/places.db whose road address names that district, so no
boundary data is needed. Each district then takes the free grid cell nearest to it, the districts far
from the province's middle first (they have the fewest good cells). The file holds names and grid
positions only, no fee values (those stay in the private dataset).
"""

from __future__ import annotations

import csv
import json
import math
import sqlite3
import statistics
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
FEE_CSV = PROJECT_DIR / "data" / "vet_fees" / "vet_fees.csv"
PLACES_DB = PROJECT_DIR / "data" / "places.db"
OUT = PROJECT_DIR / "web" / "src" / "lib" / "feeTiles.json"

# Spare cells per district: room for the shape, without a grid mostly empty.
SLACK = 1.6
# Since 2026 places' addresses name 광주 and 전라남도 as one province (src/tools/fees.MERGED_SIDO).
ADDRESS_SIDO = {"광주광역시": "전남광주통합특별시", "전라남도": "전남광주통합특별시"}


def districts() -> dict[str, list[str]]:
    by_sido: dict[str, set[str]] = {}
    with FEE_CSV.open(encoding="utf-8-sig") as file:
        for row in csv.DictReader(file):
            if row["level"] == "sigungu":
                by_sido.setdefault(row["sido"], set()).add(row["sigungu"])
    return {sido: sorted(names) for sido, names in sorted(by_sido.items())}


def centres(by_sido: dict[str, list[str]]) -> dict[tuple[str, str], tuple[float, float]]:
    points: dict[tuple[str, str], list[tuple[float, float]]] = {}
    with sqlite3.connect(PLACES_DB) as conn:
        rows = conn.execute("select road_address, longitude, latitude from place "
                            "where road_address is not null and latitude is not null").fetchall()
    for address, lon, lat in rows:
        words = address.split()
        if len(words) >= 2:
            points.setdefault((words[0], words[1]), []).append((lon, lat))
    found = {}
    for sido, names in by_sido.items():
        for name in names:
            key = (ADDRESS_SIDO.get(sido, sido), sido if name == sido else name)
            if key in points:
                lons, lats = zip(*points[key])
                found[(sido, name)] = (statistics.median(lons), statistics.median(lats))
    return found


def place_on_grid(spots: dict[str, tuple[float, float] | None]) -> tuple[int, int, dict[str, tuple[int, int]]]:
    """(columns, rows, name -> (column, row)): each located name in the free cell nearest it, the far
    ones first; a name without a location in the first free cell, reading order."""
    located = {name: spot for name, spot in spots.items() if spot}
    lat0 = statistics.mean(lat for _, lat in located.values()) if located else 36.0
    # Kilometre-like units: a degree of longitude is shorter than one of latitude.
    xy = {name: (lon * math.cos(math.radians(lat0)), -lat) for name, (lon, lat) in located.items()}
    count = len(spots)
    if count == 1:
        return 1, 1, {next(iter(spots)): (0, 0)}
    xs = [x for x, _ in xy.values()] or [0.0]
    ys = [y for _, y in xy.values()] or [0.0]
    width, height = max(max(xs) - min(xs), 1e-6), max(max(ys) - min(ys), 1e-6)
    cells = math.ceil(count * SLACK)
    columns = max(1, min(count, round(math.sqrt(cells * width / height))))
    rows = max(1, math.ceil(cells / columns))
    scaled = {name: ((x - min(xs)) / width * (columns - 1), (y - min(ys)) / height * (rows - 1))
              for name, (x, y) in xy.items()}
    middle = ((columns - 1) / 2, (rows - 1) / 2)
    free = {(c, r) for c in range(columns) for r in range(rows)}
    placed: dict[str, tuple[int, int]] = {}
    for name in sorted(scaled, key=lambda n: -math.dist(scaled[n], middle)):
        cell = min(free, key=lambda cr: (math.dist(cr, scaled[name]), cr[1], cr[0]))
        placed[name] = cell
        free.remove(cell)
    improve(placed, free, scaled)
    for name in spots:
        if name not in placed:
            cell = min(free, key=lambda cr: (cr[1], cr[0]))
            placed[name] = cell
            free.remove(cell)
    # Drop the empty rows and columns; the order of the rest stays.
    used_c = sorted({c for c, _ in placed.values()})
    used_r = sorted({r for _, r in placed.values()})
    placed = {name: (used_c.index(c), used_r.index(r)) for name, (c, r) in placed.items()}
    return len(used_c), len(used_r), placed


def improve(placed: dict, free: set, scaled: dict) -> None:
    """Swap two tiles, or move one to a free cell, while that brings tiles nearer their places: the
    greedy pass alone can leave a district on the wrong side of its neighbour (서울 중구 west of 종로구)."""
    def cost(name, cell):
        return math.dist(cell, scaled[name]) ** 2

    better = True
    while better:
        better = False
        names = list(placed)
        for i, a in enumerate(names):
            for b in names[i + 1:]:
                if cost(a, placed[b]) + cost(b, placed[a]) < cost(a, placed[a]) + cost(b, placed[b]) - 1e-9:
                    placed[a], placed[b] = placed[b], placed[a]
                    better = True
            for cell in list(free):
                if cost(a, cell) < cost(a, placed[a]) - 1e-9:
                    free.add(placed[a])
                    free.remove(cell)
                    placed[a] = cell
                    better = True


def main() -> None:
    by_sido = districts()
    found = centres(by_sido)
    out = {}
    for sido, names in by_sido.items():
        columns, rows, placed = place_on_grid({name: found.get((sido, name)) for name in names})
        missing = [name for name in names if (sido, name) not in found]
        if missing:
            print(f"{sido}: no places for {', '.join(missing)} (placed at the end)")
        out[sido] = {"columns": columns, "rows": rows,
                     "tiles": [{"name": name, "column": c, "row": r} for name, (c, r) in sorted(placed.items(), key=lambda kv: (kv[1][1], kv[1][0]))]}
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    for sido, grid in out.items():
        print(f"\n{sido} {grid['columns']}x{grid['rows']}")
        cells = {(t["column"], t["row"]): t["name"] for t in grid["tiles"]}
        for r in range(grid["rows"]):
            print(" ".join(f"{cells.get((c, r), '·'):<5}"[:5] for c in range(grid["columns"])))


if __name__ == "__main__":
    main()
