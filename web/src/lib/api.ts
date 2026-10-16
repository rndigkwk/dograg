// Calls to the RagDog API (api/, Cloud Run ragdog-api; docs/adr/0008).

import type { PetProfile } from "./profile";
import { readEvents, type StreamEvent } from "./sse";

export const API_URL = (process.env.NEXT_PUBLIC_RAGDOG_API_URL ?? "https://ragdog-api-892238791473.asia-northeast3.run.app").replace(/\/$/, "");

// This browser's random id: the API counts questions per browser (src/rate_limit.py) with it.
// The same key as the Streamlit app's (src/storage/snapshot.py CLIENT_KEY).
const CLIENT_KEY = "ragdog:v1:client";

export function clientId(): string | null {
  try {
    let id = localStorage.getItem(CLIENT_KEY);
    if (!id || !/^[0-9a-f]{32}$/.test(id)) {
      id = crypto.randomUUID().replace(/-/g, "");
      localStorage.setItem(CLIENT_KEY, id);
    }
    return id;
  } catch {
    return null; // storage blocked: the API counts by network instead
  }
}

function headers(): HeadersInit {
  const id = clientId();
  return { "Content-Type": "application/json", ...(id ? { "X-RagDog-Client": id } : {}) };
}

/** Wakes the API (Cloud Run scales to zero; the first request after a pause takes 15-27 s). */
export function warmUp(): void {
  fetch(`${API_URL}/health`).catch(() => {});
}

export type Turn = { role: "user" | "assistant"; content: string; route?: string };
export type Memory = { upto: number; summary: string };

export type ChatRequest = {
  question: string;
  history: Turn[];
  memory: Memory;
  profile: PetProfile | null;
  location: [number, number] | null;
  // Ask for a memory suggestion only once the stored profile is loaded (api/chat.py ChatRequest).
  suggest_memory: boolean;
  declined_memory: string[];
};

// The reasons under a 👎 (src/feedback_store.REASONS; the API refuses any other).
export const FEEDBACK_REASONS = ["틀린 정보", "질문과 다른 답", "근거가 부족해요", "너무 길어요", "기타"] as const;

async function post(path: string, body: unknown): Promise<boolean> {
  try {
    const response = await fetch(`${API_URL}${path}`, { method: "POST", headers: headers(), body: JSON.stringify(body) });
    return response.ok;
  } catch {
    return false;
  }
}

/** 👍/👎 on an answer (a Langfuse score; a changed vote overwrites it). */
export function sendVote(traceId: string, helpful: boolean): Promise<boolean> {
  return post("/feedback", { trace_id: traceId, helpful });
}

export function sendReason(traceId: string, reason: string): Promise<boolean> {
  return post("/feedback/reason", { trace_id: traceId, reason });
}

/** The guardian agreed to send this question and answer for review (stored masked, api/feedback.py). */
export async function sendReview(review: {
  traceId: string;
  question: string;
  answer: string;
  route?: string;
  reason?: string | null;
  evidenceRows?: Record<string, unknown>[];
}): Promise<boolean> {
  const response = await fetch(`${API_URL}/feedback/review`, {
    method: "POST",
    headers: headers(),
    body: JSON.stringify({
      trace_id: review.traceId,
      question: review.question,
      answer: review.answer,
      route: review.route ?? null,
      reason: review.reason ?? null,
      evidence_rows: (review.evidenceRows ?? []).slice(0, 12),
    }),
  }).catch(() => null);
  if (!response?.ok) return false;
  return Boolean((await response.json()).saved);
}

/** POST /chat: each event of the answer as it arrives. Throws on a refused request. */
export async function* askChat(body: ChatRequest, signal?: AbortSignal): AsyncGenerator<StreamEvent> {
  yield* postStream("/chat", body, signal);
}

export class HttpError extends Error {
  constructor(readonly status: number) {
    super(`HTTP ${status}`);
  }
}

/** POST a JSON body and read the streamed events; a refused request throws HttpError. */
export async function* postStream(path: string, body: unknown, signal?: AbortSignal): AsyncGenerator<StreamEvent> {
  const response = await fetch(`${API_URL}${path}`, { method: "POST", headers: headers(), body: JSON.stringify(body), signal });
  if (!response.ok || !response.body) throw new HttpError(response.status);
  yield* readEvents(response.body);
}
