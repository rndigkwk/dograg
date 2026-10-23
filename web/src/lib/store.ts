// Conversations kept in this browser's localStorage, in the Streamlit app's format
// (src/storage/models.py Thread/Turn, src/storage/snapshot.py keys and limits). Anything read back
// may have been edited by hand, so each record is checked and cut to the limits; bad ones are dropped.

import type { Answer, Message } from "./chat";

export const THREADS_KEY = "ragdog:v1:threads";
export const PROFILE_KEY = "ragdog:v1:profile";
export const NOTICE_KEY = "ragdog:v1:notice_seen";
// The question-limit id (api.ts CLIENT_KEY) is not here: clearing the device keeps it, so the
// limit is not reset by clearing.

export const MAX_THREADS = 20;
export const MAX_TURNS_PER_THREAD = 20;
const MAX_QUESTION_CHARS = 1000;
const MAX_ANSWER_CHARS = 4000;
const MAX_TITLE_CHARS = 30;
const MAX_THREADS_JSON_CHARS = 1_000_000; // localStorage holds about 5 MB per site
export const DEFAULT_TITLE = "새 대화";
const ROUTES = ["rag", "sql", "analysis", "none", "date", "fee"];

export type StoredTurn = { question: string; answer: string; route: string; evidence_ids: string[]; at: string };
export type Thread = { id: string; title: string; created_at: string; updated_at: string; turns: StoredTurn[] };

export interface KeyValue {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem(key: string): void;
}

/** localStorage, or null when the browser blocks it (private mode with storage off, some embeds). */
export function browserStorage(): KeyValue | null {
  try {
    const probe = "ragdog:v1:probe";
    localStorage.setItem(probe, "1");
    localStorage.removeItem(probe);
    return localStorage;
  } catch {
    return null;
  }
}

const now = () => new Date().toISOString();

function clean(value: unknown, limit: number, singleLine = false): string {
  let text = typeof value === "string" ? value : "";
  text = text.replace(/[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]/g, "");
  if (singleLine) text = text.replace(/\s+/g, " ");
  return text.trim().slice(0, limit);
}

export function makeTitle(question: string): string {
  return clean(question, MAX_TITLE_CHARS, true) || DEFAULT_TITLE;
}

function checkTurn(item: unknown): StoredTurn | null {
  if (!item || typeof item !== "object") return null;
  const t = item as Record<string, unknown>;
  if (typeof t.question !== "string" || typeof t.answer !== "string") return null;
  return {
    question: clean(t.question, MAX_QUESTION_CHARS),
    answer: clean(t.answer, MAX_ANSWER_CHARS),
    route: ROUTES.includes(t.route as string) ? (t.route as string) : "none",
    evidence_ids: Array.isArray(t.evidence_ids) ? t.evidence_ids.slice(0, 12).map((id) => clean(String(id), 64, true)).filter(Boolean) : [],
    at: typeof t.at === "string" ? t.at : now(),
  };
}

function checkThread(item: unknown): Thread | null {
  if (!item || typeof item !== "object") return null;
  const t = item as Record<string, unknown>;
  if (typeof t.id !== "string" || !/^[0-9a-f]{32}$/.test(t.id) || !Array.isArray(t.turns)) return null;
  const turns = t.turns.map(checkTurn);
  if (turns.some((turn) => turn === null)) return null;
  return {
    id: t.id,
    title: makeTitle(typeof t.title === "string" ? t.title : ""),
    created_at: typeof t.created_at === "string" ? t.created_at : now(),
    updated_at: typeof t.updated_at === "string" ? t.updated_at : now(),
    turns: (turns as StoredTurn[]).slice(-MAX_TURNS_PER_THREAD),
  };
}

/** The stored threads, newest first; invalid, repeated or extra ones dropped. */
export function loadThreads(storage: KeyValue | null): Thread[] {
  const text = storage?.getItem(THREADS_KEY);
  if (!text || text.length > MAX_THREADS_JSON_CHARS) return [];
  let data: unknown;
  try {
    data = JSON.parse(text);
  } catch {
    return [];
  }
  if (!Array.isArray(data)) return [];
  const seen = new Set<string>();
  const threads: Thread[] = [];
  for (const item of data) {
    const thread = checkThread(item);
    if (thread && !seen.has(thread.id)) {
      seen.add(thread.id);
      threads.push(thread);
    }
  }
  return sortThreads(threads).slice(0, MAX_THREADS);
}

function sortThreads(threads: Thread[]): Thread[] {
  return [...threads].sort((a, b) => (a.updated_at < b.updated_at ? 1 : a.updated_at > b.updated_at ? -1 : 0));
}

/** Writes the threads; the oldest go first when they do not fit. False when nothing could be saved. */
export function saveThreads(storage: KeyValue | null, threads: Thread[]): boolean {
  if (!storage) return false;
  let kept = sortThreads(threads).slice(0, MAX_THREADS);
  for (;;) {
    const text = JSON.stringify(kept);
    if (text.length <= MAX_THREADS_JSON_CHARS) {
      try {
        storage.setItem(THREADS_KEY, text);
        return true;
      } catch {
        // over the browser's quota: drop the oldest thread and try again
      }
    }
    if (kept.length <= 1) return false;
    kept = kept.slice(0, -1);
  }
}

function newId(): string {
  return crypto.randomUUID().replace(/-/g, "");
}

/** The threads after one answered question; a new thread (titled by the question) when `id` is null. */
export function recordTurn(threads: Thread[], id: string | null, question: string, answer: Answer): { threads: Thread[]; id: string } {
  const at = now();
  const turn: StoredTurn = checkTurn({ question, answer: answer.content, route: answer.route ?? "none", evidence_ids: [], at })!;
  const existing = id ? threads.find((thread) => thread.id === id) : undefined;
  const thread: Thread = existing
    ? { ...existing, updated_at: at, turns: [...existing.turns, turn].slice(-MAX_TURNS_PER_THREAD) }
    : { id: newId(), title: makeTitle(question), created_at: at, updated_at: at, turns: [turn] };
  return { threads: sortThreads([thread, ...threads.filter((other) => other.id !== thread.id)]).slice(0, MAX_THREADS), id: thread.id };
}

/** A stored thread as chat messages: text only (evidence and feedback are not stored). */
export function messagesOf(thread: Thread | undefined): Message[] {
  return (thread?.turns ?? []).flatMap((turn): Message[] => [
    { role: "user", content: turn.question },
    { role: "assistant", content: turn.answer, route: turn.route },
  ]);
}

/** True the first time this browser opens the app: the storage notice is shown, then marked seen. */
export function takeNotice(storage: KeyValue | null): boolean {
  if (!storage || storage.getItem(NOTICE_KEY) === "1") return false;
  storage.setItem(NOTICE_KEY, "1");
  return true;
}

/** "이 기기의 기록 모두 지우기": conversations, the dog's profile and the notice flag. */
export function clearDevice(storage: KeyValue | null): void {
  for (const key of [THREADS_KEY, PROFILE_KEY, NOTICE_KEY]) storage?.removeItem(key);
}

export const STORAGE_NOTICE =
  "대화와 반려견 정보는 이 브라우저에 저장됩니다. 서버에는 자료를 보강하려고 두 가지를 남깁니다: " +
  "답변 속 '자료에 없다'는 문장, 그리고 ‘아쉬워요’ 뒤 직접 보내 주신 질문과 답변(둘 다 전화번호 같은 개인정보는 가림). " +
  "질문 횟수 제한(한 시간 10번, 하루 30번)을 위해 알아볼 수 없게 바꾼 브라우저·접속 주소 값과 시각을 이틀 동안 둡니다. " +
  "공용 PC라면 사용 후 '이 기기의 기록 모두 지우기'로 지워 주세요.";
