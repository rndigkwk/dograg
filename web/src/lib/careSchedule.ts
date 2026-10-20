// Care schedule (2026-10-19): the guardian writes when a routine care item was last done and sees when
// it is next due. The intervals are the 동물사랑배움터 behaviour-guidance ethics guideline's
// (data/care_guides, src/tools/care_guides.py): its PDF pages 39-40, quoted in docs/wiki/data.md.
// Kept in this browser only, like the pet profile (store.ts): no account and no server.

import type { KeyValue } from "./store";

export const CARE_SCHEDULE_KEY = "ragdog:v1:care_schedule";
export const SOON_DAYS = 7;

const GUIDELINE = "건강한 반려문화 조성을 위한 행동지도 윤리 가이드라인";
const GUIDELINE_URL = "https://apms.epis.or.kr/home/kor/board.do?menuPos=16&act=detail&idx=1454";

/** Each interval in days or months, earliest and latest ("3~6개월" is 3 to 6 months). */
type Interval = { unit: "day" | "month"; min: number; max: number };

export type CareItem = { id: string; label: string; interval: Interval; wording: string; page: number };

export const CARE_ITEMS: CareItem[] = [
  { id: "heartworm", label: "심장사상충 예방약", interval: { unit: "month", min: 1, max: 1 }, wording: "매달", page: 40 },
  { id: "external", label: "외부 기생충 예방약", interval: { unit: "month", min: 1, max: 1 }, wording: "매달", page: 40 },
  { id: "deworming", label: "내부 기생충 구충제", interval: { unit: "month", min: 3, max: 6 }, wording: "3~6개월 간격", page: 40 },
  { id: "vaccine", label: "종합백신(DHPPL) 추가접종", interval: { unit: "month", min: 12, max: 12 }, wording: "매년 1회", page: 39 },
  { id: "rabies", label: "광견병 추가접종", interval: { unit: "month", min: 12, max: 12 }, wording: "매년 1회", page: 39 },
  { id: "checkup", label: "정기 건강검진", interval: { unit: "month", min: 12, max: 12 }, wording: "1년에 한 번 이상", page: 39 },
  { id: "nails", label: "발톱 손질", interval: { unit: "day", min: 14, max: 21 }, wording: "2~3주 주기", page: 39 },
];

export const SOURCE = { title: GUIDELINE, url: GUIDELINE_URL, organization: "동물사랑배움터" };

/** Last-done dates by item id, as YYYY-MM-DD. */
export type CareRecord = Record<string, string>;

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;

function parseDate(value: string): Date | null {
  if (!ISO_DATE.test(value)) return null;
  const [year, month, day] = value.split("-").map(Number);
  const date = new Date(Date.UTC(year, month - 1, day));
  // 2026-02-30 rolls over to March: not a real date.
  return date.getUTCMonth() === month - 1 && date.getUTCDate() === day ? date : null;
}

export const formatDate = (date: Date): string => date.toISOString().slice(0, 10);

const startOfDay = (date: Date): Date => new Date(Date.UTC(date.getFullYear(), date.getMonth(), date.getDate()));

function add(date: Date, unit: "day" | "month", amount: number): Date {
  if (unit === "day") return new Date(date.getTime() + amount * 86_400_000);
  // Month ends stay month ends: 1월 31일 + 1개월 is 2월 28일 (or 29일), not 3월 3일.
  const target = new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth() + amount, 1));
  const lastDay = new Date(Date.UTC(target.getUTCFullYear(), target.getUTCMonth() + 1, 0)).getUTCDate();
  target.setUTCDate(Math.min(date.getUTCDate(), lastDay));
  return target;
}

export type Due = { from: string; to: string; status: "overdue" | "due" | "soon" | "later"; days: number };

/** When the item is next due after `last`, and where today stands: overdue after the latest date,
 * due between the earliest and the latest, soon within SOON_DAYS before the earliest, later otherwise.
 * `days` counts to the earliest date. */
export function nextDue(item: CareItem, last: string, today = new Date()): Due | null {
  const done = parseDate(last);
  if (!done) return null;
  const from = add(done, item.interval.unit, item.interval.min);
  const to = add(done, item.interval.unit, item.interval.max);
  const now = startOfDay(today);
  const days = Math.round((from.getTime() - now.getTime()) / 86_400_000);
  const status = now > to ? "overdue" : days <= 0 ? "due" : days <= SOON_DAYS ? "soon" : "later";
  return { from: formatDate(from), to: formatDate(to), status, days };
}

/** Only known items with a real date that is not in the future; anything else read back is dropped. */
export function cleanRecord(raw: unknown, today = new Date()): CareRecord {
  if (!raw || typeof raw !== "object") return {};
  const latest = startOfDay(today);
  const record: CareRecord = {};
  for (const item of CARE_ITEMS) {
    const value = (raw as Record<string, unknown>)[item.id];
    const date = typeof value === "string" ? parseDate(value) : null;
    if (date && date <= latest) record[item.id] = formatDate(date);
  }
  return record;
}

/** The items due now or overdue in a record: what the visit report mentions. */
export function dueItems(record: CareRecord, today = new Date()): CareItem[] {
  return CARE_ITEMS.filter((item) => {
    const due = record[item.id] ? nextDue(item, record[item.id], today) : null;
    return due !== null && (due.status === "overdue" || due.status === "due");
  });
}

export function loadRecord(storage: KeyValue | null, today = new Date()): CareRecord {
  try {
    return cleanRecord(JSON.parse(storage?.getItem(CARE_SCHEDULE_KEY) ?? "{}"), today);
  } catch {
    return {};
  }
}

export function saveRecord(storage: KeyValue | null, record: CareRecord): void {
  try {
    if (Object.keys(record).length) storage?.setItem(CARE_SCHEDULE_KEY, JSON.stringify(record));
    else storage?.removeItem(CARE_SCHEDULE_KEY);
  } catch {
    // storage full or blocked: the schedule still shows for this visit
  }
}
