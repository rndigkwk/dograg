"""Pure straight-line ranking of hospitals stored in EPSG:5174."""

from math import asin, cos, isfinite, radians, sin, sqrt

from pyproj import Transformer

_TRANSFORMER = Transformer.from_crs("EPSG:5174", "EPSG:4326", always_xy=True)


def _valid_user(latitude: float, longitude: float) -> bool:
    return isfinite(latitude) and isfinite(longitude) and 33 <= latitude <= 39 and 124 <= longitude <= 132


def nearest_hospitals(rows: list[dict], latitude: float, longitude: float, limit: int = 10) -> list[dict]:
    try:
        latitude, longitude = float(latitude), float(longitude)
    except (TypeError, ValueError) as exc:
        raise ValueError("유효하지 않은 위치입니다.") from exc
    if not _valid_user(latitude, longitude):
        raise ValueError("위치는 대한민국 범위의 위도/경도여야 합니다.")
    ranked = []
    for row in rows:
        try:
            x, y = float(row["x_coor"]), float(row["y_coor"])
            lon, lat = _TRANSFORMER.transform(x, y)
        except (KeyError, TypeError, ValueError):
            continue
        if not _valid_user(lat, lon):
            continue
        dlat = radians(lat - latitude)
        dlon = radians(lon - longitude)
        a = sin(dlat / 2) ** 2 + cos(radians(latitude)) * cos(radians(lat)) * sin(dlon / 2) ** 2
        distance = 6371.0088 * 2 * asin(min(1, sqrt(a)))
        ranked.append({**row, "latitude": lat, "longitude": lon, "distance_km": distance})
    def order_key(row):
        hospital_id = row.get("ids")
        try:
            id_key = (0, int(hospital_id))
        except (TypeError, ValueError):
            id_key = (1, str(hospital_id))
        return row["distance_km"], id_key

    return sorted(ranked, key=order_key)[:max(0, limit)]
