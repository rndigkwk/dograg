// The place search (api/places.py, data/places.db): kinds, regions, by region, nearest, one place.

import { API_URL } from "./api";
import type { Emergency } from "./chat";

// `more`: sources stored under this kind (한국관광공사's pet travel places are pet_friendly ones).
export type Source = { title: string; url: string; rows: number; updated: string; more?: Source[] };
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

// pet_friendly details on a phone's card: the conditions first, then the information's own date
// (the source's 최종작성일; some are years old, so the card says when, not "now"). zone, allowed
// and needs come from 한국관광공사, size and restrictions from 문화정보원; a place has one or the other.
export const CARD_INFO: [key: string, label: string][] = [
  ["zone", "동반 구역"],
  ["allowed", "동반 가능 반려견"],
  ["needs", "동반 시 필요"],
  ["size", "입장 가능 크기"],
  ["restrictions", "제한사항"],
  ["extra_fee", "추가 요금"],
  ["hours", "운영시간"],
  ["written", "정보 작성일"],
];

// pet_friendly details worth a column; the rest show on the place view (app_pages/hospital.py).
export const TABLE_INFO: [key: string, label: string][] = [
  ["allowed", "동반 가능 반려견"],
  ["needs", "동반 시 필요"],
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
// pet_friendly condition filters (api/places.py). A place whose source left the condition empty never
// matches: empty is not "no restriction".
export const CONDITIONS = [
  ["large_dog", "대형견도 가능"],
  ["no_carrier", "이동장·유모차 없이"],
  ["all_areas", "실내까지 전 구역"],
] as const;
export type Conditions = Partial<Record<(typeof CONDITIONS)[number][0], boolean>>;
const conditionParams = (conditions: Conditions = {}) =>
  Object.fromEntries(Object.entries(conditions).filter(([, on]) => on).map(([name]) => [name, "true"]));

export const search = (kind: string, province: string, city?: string, conditions?: Conditions) =>
  get<{ total: number; places: Place[] }>("/places/search", { kind, province, city, limit: 1000, ...conditionParams(conditions) });
export const nearby = (kind: string, [lat, lon]: [number, number], conditions?: Conditions) =>
  get<{ places: Place[] }>("/places/nearby", { kind, lat, lon, limit: 10, ...conditionParams(conditions) });
// An urgent warning's hospitals (nearest, and nearest named 24시/응급/야간), the same /chat sends.
export const emergency = ([lat, lon]: [number, number]) => get<Emergency>("/places/emergency", { lat, lon });
export const place = (id: string) => get<Place>(`/places/${encodeURIComponent(id)}`);

/** The places a name or address contains `query` in, of `category` when one is picked. */
export function filterPlaces(places: Place[], query: string, category: string): Place[] {
  const words = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
  return places.filter((p) => (!category || p.category === category)
    && words.every((word) => `${p.name} ${p.address ?? ""}`.toLowerCase().includes(word)));
}

/** The categories among the places, most common first (카페, 펜션, 숙박…), for the filter. */
export function categoriesOf(places: Place[]): string[] {
  const counts = new Map<string, number>();
  for (const p of places) if (p.category) counts.set(p.category, (counts.get(p.category) ?? 0) + 1);
  return [...counts].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0], "ko")).map(([name]) => name);
}

/** Directions in Kakao Map to the place, or null without coordinates. */
export function directionsUrl(p: Place): string | null {
  if (p.latitude === null || p.longitude === null) return null;
  return `https://map.kakao.com/link/to/${encodeURIComponent(p.name.replace(/,/g, " "))},${p.latitude},${p.longitude}`;
}

export function located(places: Place[]): (Place & { latitude: number; longitude: number })[] {
  return places.filter((p): p is Place & { latitude: number; longitude: number } => p.latitude !== null && p.longitude !== null);
}
