// Regional animal-clinic fees (api/fees.py; the 2025 government survey from animalclinicfee.or.kr).

import { API_URL } from "./api";

export type FeeItem = { category: string; item: string; detail: string; label: string };
export type FeeValues = { mean: number; median: number; min: number; max: number };
export type SidoFee = FeeValues & { sido: string };
export type SigunguFee = FeeValues & { sido: string; sigungu: string };
export type ItemFees = {
  item: string;
  detail: string;
  category: string;
  label: string;
  national: FeeValues;
  sido: SidoFee[];
  sigungu: SigunguFee[];
  no_data: string[];
  collected: string;
  source: string;
  source_url: string;
  notice: string;
};

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(`${API_URL}${path}`);
  if (!response.ok) {
    const detail = await response.json().catch(() => null);
    throw new Error(typeof detail?.detail === "string" ? detail.detail : "진료비 자료를 불러오지 못했습니다. 잠시 뒤 다시 시도해 주세요.");
  }
  return response.json();
}

export function feeItems(): Promise<{ items: FeeItem[]; source: string; notice: string }> {
  return getJson("/fees/items");
}

export type RegionFee = {
  item: string;
  detail: string;
  label: string;
  national_median: number;
  median: number | null;
  level: "sigungu" | "sido" | null;
  region: string | null;
};
export type RegionFees = { province: string; city: string; basis: string; items: RegionFee[]; source: string; notice: string };

export function regionFees(province: string, city = ""): Promise<RegionFees> {
  return getJson(`/fees/region?${new URLSearchParams({ province, city })}`);
}

/** The place-search region of a road address: "서울특별시 강남구 …" -> ["서울특별시", "강남구"]. */
export function regionOfAddress(address: string | null): [string, string] | null {
  const words = (address ?? "").split(/\s+/).filter(Boolean);
  return words.length >= 2 ? [words[0], words[1]] : null;
}

/** "중간 11,000원 · 전국보다 1,000원 높음 (전국 10,000원)", in the fee page's words (versusNational). */
export function compareText(row: RegionFee): string {
  if (row.median === null) return `전국 중간 ${won(row.national_median)} (이 지역 자료 없음)`;
  return `중간 ${won(row.median)} · ${versusNational(row.median, row.national_median)} (전국 ${won(row.national_median)})`;
}

export function itemFees(item: FeeItem): Promise<ItemFees> {
  return getJson(`/fees?${new URLSearchParams({ item: item.item, detail: item.detail })}`);
}

export function won(value: number): string {
  return `${value.toLocaleString("ko-KR")}원`;
}

// "서울특별시" -> "서울", "전북특별자치도" -> "전북", as the survey site labels its chart.
const SHORT: Record<string, string> = {
  충청북도: "충북",
  충청남도: "충남",
  전라남도: "전남",
  전북특별자치도: "전북",
  경상북도: "경북",
  경상남도: "경남",
};

export function shortSido(sido: string): string {
  return SHORT[sido] ?? sido.replace(/(특별자치시|특별자치도|특별시|광역시|도)$/, "");
}

/** Provinces by median, highest first (ties by name), so the chart reads as a ranking. */
export function byMedian<T extends FeeValues & { sido: string }>(rows: T[]): T[] {
  return [...rows].sort((a, b) => b.median - a.median || a.sido.localeCompare(b.sido, "ko"));
}

/** How a median compares with the national one, in words: "전국보다 1,000원 높음". */
export function versusNational(value: number, national: number): string {
  const gap = value - national;
  if (gap === 0) return "전국과 같음";
  return `전국보다 ${won(Math.abs(gap))} ${gap > 0 ? "높음" : "낮음"}`;
}

/** The gap to the national median in a few characters, for a chart label: "+1,000", "−500", "±0". */
export function gapLabel(value: number, national: number): string {
  const gap = value - national;
  if (gap === 0) return "±0";
  return `${gap > 0 ? "+" : "−"}${Math.abs(gap).toLocaleString("ko-KR")}`;
}

/** The x axis of the province dot chart (2026-10-24): province medians sit close together (초진
 * 8,000~10,000원), so bars from zero all looked the same length. Dots are read by position, so the axis
 * can start near the data: the span of the medians and the national one, padded and cut at round
 * steps (1, 2 or 5 x 10^k), with the step's ticks. */
export function dotAxis(values: number[], national: number): { lo: number; hi: number; ticks: number[] } {
  const all = [...values, national];
  let lo = Math.min(...all);
  let hi = Math.max(...all);
  if (hi === lo) {
    lo -= Math.max(1, lo * 0.1);
    hi += Math.max(1, hi * 0.1);
  }
  const rough = (hi - lo) / 4;
  const power = 10 ** Math.floor(Math.log10(rough));
  const step = [1, 2, 5, 10].map((m) => m * power).find((candidate) => candidate >= rough) ?? 10 * power;
  lo = Math.max(0, Math.floor((lo - step / 2) / step) * step);
  hi = Math.ceil((hi + step / 2) / step) * step;
  const ticks: number[] = [];
  for (let tick = lo; tick <= hi + step / 2; tick += step) ticks.push(tick);
  return { lo, hi, ticks };
}

/** The items grouped by category, in the API's order. */
export function groupByCategory(items: FeeItem[]): [string, FeeItem[]][] {
  const groups = new Map<string, FeeItem[]>();
  for (const item of items) groups.set(item.category, [...(groups.get(item.category) ?? []), item]);
  return [...groups.entries()];
}
