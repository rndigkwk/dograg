// What to tell the guardian when a request to the API failed, by why it failed (2026-10-23).
// Before, every failure read "잠시 뒤 다시 질문해 주세요", even with the Wi-Fi off.

import { HttpError } from "./api";

export const OFFLINE = "인터넷 연결이 끊긴 것 같습니다. 연결을 확인하고 다시 시도해 주세요.";
export const SERVER = "서버에 잠시 문제가 생겼습니다. 다시 시도해 주세요.";

/** The message for a failed request; `fallback` when the reason is not known (the page's own wording). */
export function failureMessage(error: unknown, fallback: string, online = typeof navigator === "undefined" || navigator.onLine): string {
  if (!online) return OFFLINE;
  // fetch rejects with a TypeError when the request never got an answer (no network, DNS, CORS).
  if (error instanceof TypeError) return OFFLINE;
  if (error instanceof HttpError && error.status >= 500) return SERVER;
  return fallback;
}

/** How long the guardian has waited, as the waiting line says it. */
export function waitedText(seconds: number): string {
  return seconds < 60 ? `${seconds}초` : `${Math.floor(seconds / 60)}분 ${seconds % 60}초`;
}

// When a hint joins the waiting line: the API sleeps when unused and its first answer takes
// 15-27 s to wake (lib/api.ts warmUp); past a minute something is slower than usual.
export const COLD_HINT_AFTER = 8;
export const SLOW_AFTER = 60;
export const COLD_HINT = "처음 질문은 서버를 깨우느라 20초쯤 걸릴 수 있습니다.";
export const SLOW_HINT = "평소보다 오래 걸리고 있습니다. 기다리거나 멈추고 다시 물어볼 수 있습니다.";

/** The hint under the waiting line after `seconds`; `started` is whether the API has answered anything yet. */
export function waitingHint(seconds: number, started: boolean): string | null {
  if (seconds >= SLOW_AFTER) return SLOW_HINT;
  if (seconds >= COLD_HINT_AFTER && !started) return COLD_HINT;
  return null;
}
