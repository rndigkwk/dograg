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

export const DEFAULT_ITEM = "초진 진찰료 (체중 5kg)";

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

/** Regions by median, highest first (ties by name), so the fee page's table reads as a ranking. */
export function byMedian<T extends FeeValues & { name: string }>(rows: T[]): T[] {
  return [...rows].sort((a, b) => b.median - a.median || a.name.localeCompare(b.name, "ko"));
}

/** How a median compares with the national one, in words: "전국보다 1,000원 높음". */
export function versusNational(value: number, national: number): string {
  const gap = value - national;
  if (gap === 0) return "전국과 같음";
  return `전국보다 ${won(Math.abs(gap))} ${gap > 0 ? "높음" : "낮음"}`;
}

/** The items grouped by category, in the API's order. */
export function groupByCategory(items: FeeItem[]): [string, FeeItem[]][] {
  const groups = new Map<string, FeeItem[]>();
  for (const item of items) groups.set(item.category, [...(groups.get(item.category) ?? []), item]);
  return [...groups.entries()];
}

// The fee picker (2026-11-06 guardian-view mockup): a category, an item and, where the survey splits it,
// a weight or species, instead of one list of the survey's 34 labels. The survey's words stay in the
// figures' titles (ItemFees.label); these are only the buttons.
const CATEGORY_NAMES: Record<string, string> = {
  진찰료: "진찰",
  예방접종비: "예방접종",
  혈액검사비용: "피검사",
  영상검사비용: "영상검사",
  입원비: "입원",
  "투약/조제비": "기생충 예방",
};
const ITEM_NAMES: Record<string, string> = {
  "초진 진찰료": "처음 진찰",
  "재진 진찰료": "다시 진찰",
  "진찰에 대한 상담료": "상담",
  "종합백신 접종비": "종합백신",
  "광견병백신 접종비": "광견병",
  "켄넬코프백신 접종비": "켄넬코프",
  "인플루엔자백신 접종비": "인플루엔자",
  "코로나바이러스백신 접종비": "코로나바이러스",
  "전혈구 검사비와 판독료": "전혈구(CBC)",
  "혈액화학 검사비와 판독료": "혈액화학",
  "전해질 검사비와 판독료": "전해질",
  "엑스선 촬영비와 판독료": "엑스레이",
  "초음파 검사비와 판독료": "초음파",
  "컴퓨터단층촬영검사(CT)비와 판독료": "CT",
  "자기공명영상검사(MRI)비와 판독료": "MRI",
  입원비: "하루 입원",
  "심장사상충 예방비": "심장사상충",
  "외부기생충 예방비": "외부기생충",
};

export const categoryName = (category: string): string => CATEGORY_NAMES[category] ?? category;
export const itemName = (item: string): string => ITEM_NAMES[item] ?? item;

/** "체중 5kg" → "5kg", "개 체중 10kg" → "개 10kg"; "기타 상담 행위" and empty details have no button. */
export function variantName(detail: string): string {
  return detail.replace(/체중\s*/, "");
}

/** The survey's categories in the API's order. */
export function categoriesOf(items: FeeItem[]): string[] {
  return [...new Set(items.map((item) => item.category))];
}

/** The items of a category, each once, in the API's order. */
export function itemsOf(items: FeeItem[], category: string): string[] {
  return [...new Set(items.filter((item) => item.category === category).map((item) => item.item))];
}

/** The rows of one item: one per weight or species, or a single row. */
export function variantsOf(items: FeeItem[], item: string): FeeItem[] {
  return items.filter((row) => row.item === item);
}

const kgOf = (detail: string): number | null => {
  const match = /(\d+)\s*kg/.exec(detail);
  return match ? Number(match[1]) : null;
};

/** The variant for the dog's weight: the nearest surveyed weight (a dog's row before a cat's), or the first. */
export function variantFor(variants: FeeItem[], weightKg?: number | null): FeeItem {
  const dogs = variants.filter((row) => !row.detail.includes("고양이"));
  const pool = dogs.length ? dogs : variants;
  if (!weightKg) return pool[0];
  let best = pool[0];
  for (const row of pool) {
    const kg = kgOf(row.detail);
    const bestKg = kgOf(best.detail);
    if (kg !== null && (bestKg === null || Math.abs(kg - weightKg) < Math.abs(bestKg - weightKg))) best = row;
  }
  return best;
}
