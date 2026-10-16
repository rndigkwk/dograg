import type { Page, Request } from "@playwright/test";

import { FAKE_API } from "../playwright.config";

type Event = [kind: string, data: unknown];

export const sse = (events: Event[]) => events.map(([kind, data]) => `event: ${kind}\ndata: ${JSON.stringify(data)}\n\n`).join("");

export function result(answer: string, extra: Record<string, unknown> = {}): Event {
  return [
    "result",
    {
      answer,
      route: "rag",
      evidence_rows: [],
      hospital_rows: [],
      safety_notice: null,
      abstained: false,
      trace_id: "0123456789abcdef0123456789abcdef",
      memory: { upto: 0, summary: "" },
      ...extra,
    },
  ];
}

/** Answers /chat with the next event list in `replies` (the last one repeats), and records the requests.
 * `json` answers other GET paths (pathname -> body, or a function of the URL). */
export async function fakeApi(
  page: Page,
  replies: Event[][],
  json: Record<string, unknown | ((url: URL) => unknown)> = {},
  streams: Record<string, Event[] | number> = {}, // other POST paths: their events, or an HTTP status to refuse with
) {
  const chats: Record<string, unknown>[] = [];
  const gets: string[] = [];
  const posts: { path: string; body: Record<string, unknown> }[] = [];
  const chatHeaders: Record<string, string>[] = [];
  const feedback: { path: string; body: Record<string, unknown> }[] = [];
  await page.route(`${FAKE_API}/**`, async (route) => {
    const request: Request = route.request();
    const path = new URL(request.url()).pathname;
    const cors = { "Access-Control-Allow-Origin": "*", "Access-Control-Allow-Headers": "*" };
    if (request.method() === "OPTIONS") return route.fulfill({ status: 204, headers: cors });
    if (path === "/health") return route.fulfill({ json: { status: "ok", commit: "test" }, headers: cors });
    if (path === "/chat") {
      chats.push(request.postDataJSON());
      chatHeaders.push(request.headers());
      const events = replies[Math.min(chats.length - 1, replies.length - 1)];
      return route.fulfill({ body: sse(events), headers: { ...cors, "Content-Type": "text/event-stream" } });
    }
    if (request.method() === "POST" && path in streams) {
      posts.push({ path, body: request.postDataJSON() });
      const reply = streams[path];
      if (typeof reply === "number") return route.fulfill({ status: reply, json: { detail: "refused" }, headers: cors });
      return route.fulfill({ body: sse(reply), headers: { ...cors, "Content-Type": "text/event-stream" } });
    }
    if (request.method() === "GET" && path in json) {
      const url = new URL(request.url());
      gets.push(`${path}${url.search}`);
      const body = json[path];
      return route.fulfill({ json: typeof body === "function" ? body(url) : body, headers: cors });
    }
    if (path.startsWith("/feedback")) {
      feedback.push({ path, body: request.postDataJSON() });
      return route.fulfill({ json: { recorded: true, saved: true }, headers: cors });
    }
    return route.fulfill({ status: 404, headers: cors });
  });
  return { chats, feedback, gets, posts, chatHeaders };
}

/** Types a question and sends it with Enter. */
export async function ask(page: Page, question: string) {
  const box = page.getByRole("textbox", { name: "질문" });
  await box.fill(question);
  await box.press("Enter");
}
