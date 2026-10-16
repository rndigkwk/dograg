// The dog's profile ("우리 아이 정보"), kept in this browser only, in the Streamlit app's format
// (src/storage/models.py PetProfile, stored as JSON without empty fields). The API checks it again.

import { type KeyValue, PROFILE_KEY } from "./store";

export type PetProfile = {
  name?: string | null;
  breed?: string | null;
  birth_month?: string | null; // "YYYY-MM-01"
  weight_kg?: number | null;
  neutered?: boolean | null;
  conditions?: string[];
  medications?: string[];
  allergies?: string[];
  procedures?: string[];
};

const MAX_TEXT = 30;
const MAX_ITEMS = 10;
const LISTS = ["conditions", "medications", "allergies", "procedures"] as const;
const PUPPY_MAX_MONTHS = 12; // src/tools/profile.py
const ADULT_MAX_MONTHS = 6 * 12 + 11;

function text(value: unknown): string | null {
  if (typeof value !== "string") return null;
  return value.replace(/[\x00-\x1f\x7f]/g, "").replace(/\s+/g, " ").trim().slice(0, MAX_TEXT) || null;
}

export function splitItems(value: string): string[] {
  return value.split(/[,\n]/).map((item) => item.trim()).filter(Boolean);
}

function items(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return [...new Set(value.map(text).filter((item): item is string => Boolean(item)))].slice(0, MAX_ITEMS);
}

function birthMonth(value: unknown, today: Date): string | null {
  if (typeof value !== "string" || !/^\d{4}-\d{2}(-\d{2})?$/.test(value)) return null;
  const month = `${value.slice(0, 7)}-01`;
  const thisMonth = `${today.toISOString().slice(0, 7)}-01`;
  return month >= "1990-01-01" && month <= thisMonth ? month : null;
}

/** A profile with every field checked; fields that fail are dropped, as in PetProfile. */
export function cleanProfile(raw: unknown, today = new Date()): PetProfile {
  if (!raw || typeof raw !== "object") return {};
  const r = raw as Record<string, unknown>;
  const profile: PetProfile = {};
  if (text(r.name)) profile.name = text(r.name);
  if (text(r.breed)) profile.breed = text(r.breed);
  const month = birthMonth(r.birth_month, today);
  if (month) profile.birth_month = month;
  if (typeof r.weight_kg === "number" && r.weight_kg > 0 && r.weight_kg < 150) profile.weight_kg = r.weight_kg;
  if (typeof r.neutered === "boolean") profile.neutered = r.neutered;
  for (const key of LISTS) {
    const list = items(r[key]);
    if (list.length) profile[key] = list;
  }
  return profile;
}

export function isEmpty(profile: PetProfile | null | undefined): boolean {
  return !profile || Object.keys(cleanProfile(profile)).length === 0;
}

export function loadProfile(storage: KeyValue | null): PetProfile | null {
  const raw = storage?.getItem(PROFILE_KEY);
  if (!raw) return null;
  try {
    const profile = cleanProfile(JSON.parse(raw));
    return isEmpty(profile) ? null : profile;
  } catch {
    return null;
  }
}

export function saveProfile(storage: KeyValue | null, profile: PetProfile | null): void {
  if (!storage) return;
  const clean = cleanProfile(profile);
  if (isEmpty(clean)) storage.removeItem(PROFILE_KEY);
  else storage.setItem(PROFILE_KEY, JSON.stringify(clean));
}

/** "약 3살 (성견)" from the birth month (src/tools/profile.describe_age). */
export function describeAge(birth: string, today = new Date()): string {
  const [year, month] = birth.split("-").map(Number);
  const months = Math.max(0, (today.getFullYear() - year) * 12 + today.getMonth() + 1 - month);
  const stage = months <= PUPPY_MAX_MONTHS ? "자견" : months <= ADULT_MAX_MONTHS ? "성견" : "노령견";
  return `${months < 24 ? `${months}개월` : `약 ${Math.floor(months / 12)}살`} (${stage})`;
}

/** One line for the list and the save suggestion (src/tools/profile.profile_summary). */
export function profileSummary(profile: PetProfile, today = new Date()): string {
  const lines: string[] = [];
  if (profile.name) lines.push(`이름: ${profile.name}`);
  if (profile.breed) lines.push(`견종: ${profile.breed}`);
  if (profile.birth_month) lines.push(`나이: ${describeAge(profile.birth_month, today)}`);
  if (profile.weight_kg) lines.push(`체중: ${profile.weight_kg}kg`);
  if (profile.neutered !== undefined && profile.neutered !== null) lines.push(`중성화: ${profile.neutered ? "함" : "안 함"}`);
  const labels: [string, string[] | undefined][] = [
    ["지병", profile.conditions],
    ["복용약", profile.medications],
    ["알레르기", profile.allergies],
    ["수술·시술", profile.procedures],
  ];
  for (const [label, list] of labels) if (list?.length) lines.push(`${label}: ${list.join(", ")}`);
  return lines.join(" · ") || "등록된 정보 없음";
}

/** A memory suggestion from /chat (api/chat.py memory_event). */
export type MemorySuggestion = { profile: PetProfile; summary: string; update: boolean };
