// What the chat screen shows, built from the /chat events (api/chat.py) in order. Pure, so the
// order rules are tested without a browser (chat.test.ts).

import type { StreamEvent } from "./sse";
import type { Memory, Turn } from "./api";
import { cleanProfile, type MemorySuggestion } from "./profile";

export type Hospital = { name: string; distance_km: number; phone?: string | null; road_address?: string | null; lot_address?: string | null };
export type Emergency = { nearest?: Hospital[]; night?: Hospital[] };

export type Answer = {
  role: "assistant";
  content: string;
  route?: string;
  abstained?: boolean;
  traceId?: string | null;
  evidenceRows?: Record<string, unknown>[];
  hospitalRows?: Record<string, unknown>[];
  safetyNotice?: string | null;
  urgent?: { notice: string; hospitals: Emergency } | null;
  // Not an answer: the question limit or a failure. Shown, but not sent back as history.
  notice?: "limited" | "error";
};
export type Question = { role: "user"; content: string };
export type Message = Question | Answer;

/** The answer being written: progress line, places found so far, its evidence once graded, text so far. */
export type Pending = { step: string; places: string; evidence: Record<string, unknown>[]; text: string; answer: Answer };

export const FIRST_STEP = "질문을 확인하고 있습니다…";

// The home page's question box hands its question to the chat page through this tab's storage, not
// the URL (a question can carry health or personal details that would stay in history and logs).
export const ASK_KEY = "ragdog:v1:home_question";
export const MAX_QUESTION_CHARS = 1000; // the chat box's maxLength

/** Keeps a question for the chat page to ask; false when storage is blocked. */
export function askLater(question: string, storage: Pick<Storage, "setItem"> | null = safeSession()): boolean {
  const text = question.trim().slice(0, MAX_QUESTION_CHARS);
  if (!text || !storage) return false;
  try {
    storage.setItem(ASK_KEY, text);
    return true;
  } catch {
    return false;
  }
}

/** The kept question, taken out so it is asked once. */
export function takeAsked(storage: Pick<Storage, "getItem" | "removeItem"> | null = safeSession()): string | null {
  if (!storage) return null;
  try {
    const text = storage.getItem(ASK_KEY);
    storage.removeItem(ASK_KEY);
    return text?.trim() ? text.slice(0, MAX_QUESTION_CHARS) : null;
  } catch {
    return null;
  }
}

function safeSession(): Storage | null {
  try {
    return typeof window === "undefined" ? null : window.sessionStorage;
  } catch {
    return null;
  }
}

export function startPending(): Pending {
  return { step: FIRST_STEP, places: "", evidence: [], text: "", answer: { role: "assistant", content: "" } };
}

/** The pending answer after one event; `done` when the stream has nothing more to show for it. */
export function applyEvent(pending: Pending, { kind, data }: StreamEvent): { pending: Pending; memory?: Memory; suggestion?: MemorySuggestion } {
  const d = data as Record<string, unknown>;
  switch (kind) {
    case "step":
      return { pending: pending.text ? pending : { ...pending, step: String(d.message ?? pending.step) } };
    case "places":
      return { pending: { ...pending, places: String(d.text ?? "") } };
    case "evidence": // the health answer's evidence, sent while the answer is still being written
      return { pending: { ...pending, evidence: Array.isArray(d.rows) ? (d.rows as Record<string, unknown>[]) : [] } };
    case "token":
      return { pending: { ...pending, text: pending.text + String(d.text ?? "") } };
    case "urgent":
      return { pending: { ...pending, answer: { ...pending.answer, urgent: { notice: String(d.notice), hospitals: (d.hospitals ?? {}) as Emergency } } } };
    case "limited":
      return { pending: { ...pending, answer: { ...pending.answer, content: String(d.message), notice: "limited" } } };
    case "error":
      return { pending: { ...pending, answer: { ...pending.answer, content: String(d.message), notice: "error" } } };
    case "result":
      return {
        pending: {
          ...pending,
          answer: {
            ...pending.answer,
            content: String(d.answer ?? ""),
            route: d.route as string,
            abstained: Boolean(d.abstained),
            traceId: (d.trace_id as string | null) ?? null,
            evidenceRows: (d.evidence_rows as Record<string, unknown>[]) ?? [],
            hospitalRows: (d.hospital_rows as Record<string, unknown>[]) ?? [],
            // The urgent warning already sits on top; the result repeats it as safety_notice.
            safetyNotice: pending.answer.urgent ? null : ((d.safety_notice as string | null) ?? null),
          },
        },
        memory: d.memory as Memory | undefined,
      };
    case "memory": // after the result: facts about the dog to offer for saving
      return { pending, suggestion: { profile: cleanProfile(d.profile), summary: String(d.summary ?? ""), update: Boolean(d.update) } };
    default:
      return { pending };
  }
}

/** The finished message for the conversation (the streamed text when no result arrived). */
export function finish(pending: Pending, failed: string): Answer {
  const { answer } = pending;
  if (answer.content) return answer;
  if (pending.text) return { ...answer, content: pending.text, notice: "error" };
  return { ...answer, content: failed, notice: "error" };
}

/** The turns the API gets as the conversation so far: answers only, no notices (api/chat.py MAX_TURNS). */
export function historyOf(messages: Message[], maxTurns = 40): Turn[] {
  const turns: Turn[] = [];
  messages.forEach((message, index) => {
    if (message.role === "user") {
      const reply = messages[index + 1];
      if (reply?.role === "assistant" && !reply.notice) {
        turns.push({ role: "user", content: message.content });
        turns.push({ role: "assistant", content: reply.content, ...(reply.route ? { route: reply.route } : {}) });
      }
    }
  });
  return turns.slice(-maxTurns);
}

/** Single tildes are ranges in Korean text ("5~10알"), not strikethrough (src/ui.plain_tildes). */
export function plainTildes(text: string): string {
  return text.replace(/~/g, "\\~");
}
