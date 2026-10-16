// The place search (api/places.py, data/places.db): kinds, regions, by region, nearest, one place.

import { API_URL } from "./api";

export type Source = { title: string; url: string; rows: number; updated: string };
export type Kind = { kind: string; label: string; has_location: boolean; source: Source | null };
export type Place = {
  id: string;
  kind: string;
  name: string;
  address: string | null;
  phone: string | null;
  homepage: string | null;
  category: string | null;
  latitude: number | null;
  longitude: number | null;
  info: Record<string, string>;
  info_lines: string[];
  distance_km?: number;
};

// pet_friendly details worth a column; the rest show on the place view (app_pages/hospital.py).
export const TABLE_INFO: [key: string, label: string][] = [
  ["size", "입장 가능 크기"],
  ["restrictions", "제한사항"],
  ["extra_fee", "추가 요금"],
  ["hours", "운영시간"],
];

async function get<T>(path: string, params: Record<string, string | number | undefined> = {}): Promise<T> {
  const query = new URLSearchParams(Object.entries(params).filter(([, v]) => v !== undefined).map(([k, v]) => [k, String(v)]));
  const response = await fetch(`${API_URL}${path}${query.size ? `?${query}` : ""}`);
  if (!response.ok) {
    const detail = await response.json().catch(() => null);
    throw new Error(typeof detail?.detail === "string" ? detail.detail : `places ${response.status}`);
  }
  return response.json();
}

export const kinds = () => get<Kind[]>("/places/kinds");
export const regions = () => get<Record<string, string[]>>("/places/regions");
export const search = (kind: string, province: string, city?: string) =>
  get<{ total: number; places: Place[] }>("/places/search", { kind, province, city, limit: 1000 });
export const nearby = (kind: string, [lat, lon]: [number, number]) => get<{ places: Place[] }>("/places/nearby", { kind, lat, lon, limit: 10 });
export const place = (id: string) => get<Place>(`/places/${encodeURIComponent(id)}`);

export function located(places: Place[]): (Place & { latitude: number; longitude: number })[] {
  return places.filter((p): p is Place & { latitude: number; longitude: number } => p.latitude !== null && p.longitude !== null);
}
