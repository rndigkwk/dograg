import { expect, type Page, type Request, test } from "@playwright/test";

import { FAKE_API } from "../playwright.config";
import { ask, fakeApi, result } from "./fake-api";

// "지난 상담 기억" (ADR-0009) with a fake session and a fake Supabase (no real account is touched).
const SUPABASE = "https://ffdahevkdymdaxcexkth.supabase.co";
const STORAGE_KEY = "sb-ffdahevkdymdaxcexkth-auth-token";
const USER = "00000000-0000-4000-8000-0000000000aa";
const TOKEN = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIwMDAwMDAwMC0wMDAwLTQwMDAtODAwMC0wMDAwMDAwMDAwYWEifQ.fake";
const cors = { "Access-Control-Allow-Origin": "*", "Access-Control-Allow-Headers": "*", "Access-Control-Allow-Methods": "*" };
type Row = Record<string, unknown>;

const user = (metadata: Row) => ({
  id: USER,
  aud: "authenticated",
  role: "authenticated",
  email: "guardian@example.test",
  app_metadata: { provider: "google" },
  user_metadata: metadata,
});

async function signIn(page: Page, metadata: Row = {}) {
  const session = { access_token: TOKEN, refresh_token: "fake-refresh", token_type: "bearer", expires_in: 3600, expires_at: Math.floor(Date.now() / 1000) + 3600, user: user(metadata) };
  await page.addInitScript(([key, value]) => localStorage.setItem(key, value), [STORAGE_KEY, JSON.stringify(session)]);
}

/** The account's tables in memory (notes, plus empty conversations and profile) and the settings updates. */
async function fakeAccount(page: Page, notes: Row[] = [], metadata: Row = {}) {
  const tables: Record<string, Row[]> = { ragdog_user_notes: [...notes], ragdog_user_threads: [], ragdog_user_profile: [] };
  const settings: Row[] = [];
  const writes: { method: string; table: string; body: unknown; auth: string | null }[] = [];
  await page.route(`${SUPABASE}/rest/v1/**`, async (route) => {
    const request: Request = route.request();
    const url = new URL(request.url());
    const table = url.pathname.split("/").pop()!;
    if (request.method() === "OPTIONS") return route.fulfill({ status: 204, headers: cors });
    if (request.method() === "GET") return route.fulfill({ json: tables[table] ?? [], headers: cors });
    // count: "exact", head: true -> PostgREST answers HEAD with the count in Content-Range.
    if (request.method() === "HEAD") return route.fulfill({ status: 200, headers: { ...cors, "Access-Control-Expose-Headers": "Content-Range", "Content-Range": `*/${(tables[table] ?? []).length}` } });
    const body = request.postData() ? request.postDataJSON() : null;
    writes.push({ method: request.method(), table, body, auth: request.headers()["authorization"] ?? null });
    if (request.method() === "POST") {
      const n = tables[table].length + 1;
      tables[table] = [{ note_id: `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`, created_at: "2026-10-17T03:00:00Z", user_id: USER, ...body }, ...tables[table]];
      return route.fulfill({ status: 201, json: [], headers: cors });
    }
    if (request.method() === "DELETE") {
      const id = url.searchParams.get("note_id")?.replace(/^eq\./, "");
      tables[table] = id && !id.startsWith("not.") ? tables[table].filter((r) => r.note_id !== id) : [];
      return route.fulfill({ status: 204, headers: cors });
    }
    return route.fulfill({ status: 405, headers: cors });
  });
  await page.route(`${SUPABASE}/auth/v1/**`, async (route) => {
    const request = route.request();
    if (request.method() === "OPTIONS") return route.fulfill({ status: 204, headers: cors });
    if (request.method() === "PUT" && new URL(request.url()).pathname.endsWith("/user")) {
      const data = (request.postDataJSON() as { data: Row }).data;
      settings.push(data);
      Object.assign(metadata, data);
      return route.fulfill({ json: user({ ...metadata }), headers: cors });
    }
    return route.fulfill({ status: 204, headers: cors });
  });
  return { tables, settings, writes };
}

const NOTE = "보리 설사 이틀째. 물은 잘 마심. 이틀 넘거나 혈변이면 병원.";

test("a signed-in guardian keeps a consultation as a note, and the next question carries it", async ({ page }) => {
  await signIn(page);
  const account = await fakeAccount(page);
  const api = await fakeApi(page, [[result("설사가 이틀 넘으면 병원에 가세요.", { route: "rag" })]]);
  const notes: Row[] = [];
  await page.route(`${FAKE_API}/memory/note`, async (route) => {
    if (route.request().method() === "OPTIONS") return route.fulfill({ status: 204, headers: cors });
    notes.push({ body: route.request().postDataJSON(), auth: route.request().headers()["authorization"] ?? null });
    return route.fulfill({ json: { note: NOTE, date: "2026-10-17" }, headers: cors });
  });
  await page.goto("/chat");

  await ask(page, "보리가 이틀째 설사해요");
  await page.getByRole("button", { name: "🗂 이 상담 기억하기" }).click();
  const box = page.getByRole("textbox", { name: "기억할 내용 (고쳐 쓸 수 있어요)" });
  await expect(box).toHaveValue(NOTE);
  expect(notes[0]).toMatchObject({ body: { question: "보리가 이틀째 설사해요", answer: "설사가 이틀 넘으면 병원에 가세요." }, auth: `Bearer ${TOKEN}` });
  expect(api.chats[0].notes).toBeUndefined(); // off by default: nothing was sent

  await box.fill(`${NOTE} 사료 바꾼 뒤 시작.`);
  await expect(page.getByRole("checkbox", { name: /새 질문에 지난 상담 기억 사용/ })).toBeChecked();
  await page.getByRole("button", { name: "저장" }).click();
  await expect(page.getByText("기억했습니다.")).toBeVisible();
  expect(account.writes.find((w) => w.table === "ragdog_user_notes")).toMatchObject({ method: "POST", body: { note: `${NOTE} 사료 바꾼 뒤 시작.` }, auth: `Bearer ${TOKEN}` });
  expect(account.settings).toEqual([{ consultation_notes: true }]);

  await ask(page, "또 설사해요");
  await expect.poll(() => api.chats.length).toBe(2);
  expect(api.chats[1].notes).toEqual([{ date: expect.stringMatching(/^2026-10-1[78]$/), text: `${NOTE} 사료 바꾼 뒤 시작.` }]);
});

test("a full account (30 notes) is sent to the memory page, without writing a note", async ({ page }) => {
  const full = Array.from({ length: 30 }, (_, i) => ({
    note_id: `00000000-0000-4000-8000-${String(i + 1).padStart(12, "0")}`,
    note: `기록 ${i + 1}`,
    created_at: "2026-10-10T03:00:00Z",
    thread_id: null,
  }));
  await signIn(page, { consultation_notes: true });
  await fakeAccount(page, full, { consultation_notes: true });
  await fakeApi(page, [[result("설사가 이틀 넘으면 병원에 가세요.", { route: "rag" })]]);
  let written = 0;
  await page.route(`${FAKE_API}/memory/note`, (route) => {
    written += 1;
    return route.fulfill({ status: 500, headers: cors });
  });
  await page.goto("/chat");
  await ask(page, "보리가 이틀째 설사해요");
  await page.getByRole("button", { name: "🗂 이 상담 기억하기" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "기록이 30개로 가득 찼어요." })).toBeVisible();
  await expect(page.getByRole("link", { name: "기억 화면에서 지운 뒤" })).toHaveAttribute("href", "/memory");
  expect(written).toBe(0);
});

test("the memory page shows the notes, deletes one or all, and turns the memory off", async ({ page }) => {
  const stored = [
    { note_id: "00000000-0000-4000-8000-000000000001", note: "귀를 자주 긁음, 귀 세정 안내", created_at: "2026-10-12T03:00:00Z", thread_id: null },
    { note_id: "00000000-0000-4000-8000-000000000002", note: "설사 이틀째, 이틀 넘으면 병원", created_at: "2026-10-15T03:00:00Z", thread_id: null },
  ];
  await signIn(page, { consultation_notes: true });
  const account = await fakeAccount(page, stored, { consultation_notes: true });
  await page.goto("/memory");
  await expect(page.getByText("새 질문에 지난 상담 기억 사용: 켜짐")).toBeVisible();
  const list = page.getByRole("region", { name: "저장한 상담 기록" });
  await expect(list.getByRole("listitem")).toHaveCount(2);

  await list.getByRole("button", { name: /2026-10-1[23] 기록 지우기/ }).click();
  await expect(list.getByRole("listitem")).toHaveCount(1);
  expect(account.writes.at(-1)).toMatchObject({ method: "DELETE", table: "ragdog_user_notes" });

  page.once("dialog", (dialog) => dialog.accept());
  await list.getByRole("button", { name: "모두 지우기" }).click();
  await expect(list.getByText("아직 저장한 기록이 없습니다.", { exact: false })).toBeVisible();

  await page.getByRole("switch").click();
  await expect(page.getByText("새 질문에 지난 상담 기억 사용: 꺼짐")).toBeVisible();
  expect(account.settings).toEqual([{ consultation_notes: false }]);
});

test("signed out, no note button and the memory page asks to sign in", async ({ page }) => {
  await fakeApi(page, [[result("설사가 이틀 넘으면 병원에 가세요.", { route: "rag" })]]);
  await page.goto("/chat");
  await ask(page, "보리가 이틀째 설사해요");
  await expect(page.getByText("설사가 이틀 넘으면 병원에 가세요.")).toBeVisible();
  await expect(page.getByRole("button", { name: "🗂 이 상담 기억하기" })).toHaveCount(0);
  await page.goto("/memory");
  await expect(page.getByText("지난 상담 기억은 로그인한 경우에만 쓸 수 있습니다.", { exact: false })).toBeVisible();
});
