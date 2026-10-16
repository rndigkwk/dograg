// The data page's numbers (api/stats.py GET /stats/overview, src/data_stats.py).

import { API_URL } from "./api";

export type Count = { label: string; count: number };
export type PlaceSource = {
  kind: string;
  label: string;
  title: string;
  url: string;
  source_rows: number;
  rows: number;
  with_location: number;
  with_phone: number;
  updated: string;
  notes: string[];
};
export type Overview = { diseases: Count[]; departments: Count[]; hospitals_by_province: Count[]; place_sources: PlaceSource[] };

export async function overview(): Promise<Overview> {
  const response = await fetch(`${API_URL}/stats/overview`);
  if (!response.ok) {
    const detail = await response.json().catch(() => null);
    throw new Error(typeof detail?.detail === "string" ? detail.detail : "데이터 수치를 불러오지 못했습니다. 잠시 뒤 다시 시도해 주세요.");
  }
  return response.json();
}

/** "97%" of `part` in `whole` (0% when there is nothing). */
export function percent(part: number, whole: number): string {
  return whole ? `${Math.round((part / whole) * 100)}%` : "0%";
}
