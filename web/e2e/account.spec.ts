import { expect, type Page, type Request, test } from "@playwright/test";

import { ask, fakeApi, result } from "./fake-api";

// Signed-in flows with a fake session and a fake Supabase REST API (no real account is touched).
const SUPABASE = "https://ffdahevkdymdaxcexkth.supabase.co";
const STORAGE_KEY = "sb-ffdahevkdymdaxcexkth-auth-token";
const USER = "00000000-0000-4000-8000-0000000000aa";
const TOKEN = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIwMDAwMDAwMC0wMDAwLTQwMDAtODAwMC0wMDAwMDAwMDAwYWEifQ.fake";

type Row = Record<string, unknown>;

async function signIn(page: Page) {
  const session = {
    access_token: TOKEN,
    refresh_token: "fake-refresh",
    token_type: "bearer",
    expires_in: 3600,
    expires_at: Math.floor(Date.now() / 1000) + 3600,
    user: { id: USER, aud: "authenticated", role: "authenticated", email: "guardian@example.test", app_metadata: { provider: "google" }, user_metadata: {} },
  };
  await page.addInitScript(
    ([key, value]) => {
      if (!sessionStorage.getItem("signed-out")) localStorage.setItem(key, value);
    },
    [STORAGE_KEY, JSON.stringify(session)],
  );
}

/** ragdog_user_threads / ragdog_user_profile in memory; records every call and the token it carried. */
async function fakeAccount(page: Page, threads: Row[] = [], profile: Row | null = null) {
  const tables: Record<string, Row[]> = { ragdog_user_threads: [...threads], ragdog_user_profile: profile ? [{ user_id: USER, profile }] : [] };
  const calls: { method: string; table: string; query: string; auth: string | null; body: unknown }[] = [];
  await page.route(`${SUPABASE}/rest/v1/**`, async (route) => {
    const request: Request = route.request();
    const url = new URL(request.url());
    const table = url.pathname.split("/").pop()!;
    const cors = { "Access-Control-Allow-Origin": "*", "Access-Control-Allow-Headers": "*", "Access-Control-Allow-Methods": "*" };
    if (request.method() === "OPTIONS") return route.fulfill({ status: 204, headers: cors });
    const body = request.postData() ? request.postDataJSON() : null;
    calls.push({ method: request.method(), table, query: url.search, auth: request.headers()["authorization"] ?? null, body });
    if (url.pathname.endsWith("/rpc/delete_my_account")) {
      // The database deletes the caller's account; its rows go with it (on delete cascade).
      tables.ragdog_user_threads = [];
      tables.ragdog_user_profile = [];
      return route.fulfill({ json: true, headers: cors });
    }
    if (request.method() === "GET") return route.fulfill({ json: tables[table], headers: cors });
    if (request.method() === "POST") {
      const key = table === "ragdog_user_threads" ? "thread_id" : "user_id";
      const rows = (Array.isArray(body) ? body : [body]) as Row[];
      for (const row of rows) tables[table] = [...tables[table].filter((r) => r[key] !== (row[key] ?? USER)), { user_id: USER, ...row }];
      return route.fulfill({ status: 201, json: [], headers: cors });
    }
    if (request.method() === "DELETE") {
      const ids = url.searchParams.get("thread_id")?.match(/in\.\((.*)\)/)?.[1].split(",").map((id) => id.replace(/"/g, ""));
      tables[table] = ids ? tables[table].filter((r) => !ids.includes(String(r.thread_id))) : [];
      return route.fulfill({ status: 204, headers: cors });
    }
    return route.fulfill({ status: 405, headers: cors });
  });
  await page.route(`${SUPABASE}/auth/v1/**`, (route) => route.fulfill({ status: 204, headers: { "Access-Control-Allow-Origin": "*", "Access-Control-Allow-Headers": "*" } }));
  return { tables, calls };
}

const thread = (n: number) => ({
  thread_id: n.toString(16).padStart(32, "0"),
  title: `계정 대화 ${n}`,
  turns: [{ question: `계정 질문 ${n}`, answer: `계정 답 ${n}`, route: "rag", evidence_ids: [], at: "2026-10-01T00:00:00Z" }],
  created_at: "2026-10-01T00:00:00Z",
  updated_at: `2026-10-0${n}T00:00:00Z`,
});

const openList = async (page: Page) => {
  const toggle = page.getByRole("button", { name: /^대화 기록/ });
  if ((await toggle.isVisible()) && (await toggle.getAttribute("aria-expanded")) !== "true") await toggle.click();
};

test("signed in, conversations are read from and saved to the account, with the user's token", async ({ page }) => {
  await signIn(page);
  const account = await fakeAccount(page, [thread(1)]);
  const api = await fakeApi(page, [[result("계정에 저장될 답")]]);
  await page.goto("/chat");
  await expect(page.getByRole("button", { name: "로그아웃" })).toBeVisible();
  await openList(page);
  await expect(page.getByText("계정에 저장됩니다").filter({ visible: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "계정 대화 1" }).filter({ visible: true })).toBeVisible();

  await ask(page, "새 질문이에요");
  await expect(page.getByLabel("대화", { exact: true }).getByText("계정에 저장될 답")).toBeVisible();
  await expect.poll(() => account.tables.ragdog_user_threads.length).toBe(2);
  const write = account.calls.find((call) => call.method === "POST" && call.table === "ragdog_user_threads")!;
  expect(write.auth).toBe(`Bearer ${TOKEN}`);
  expect(write.query).toContain("on_conflict=user_id%2Cthread_id");
  expect(write.body).not.toHaveProperty("user_id"); // the database fills it from the token
  // The API counts this question by account: the token goes with it.
  expect(api.chatHeaders[0]["authorization"]).toBe(`Bearer ${TOKEN}`);
  // Nothing of the account is written to this browser.
  expect(await page.evaluate(() => localStorage.getItem("ragdog:v1:threads"))).toBeNull();
});

test("signing in offers to move this browser's records into the account", async ({ page }) => {
  await page.addInitScript(() => {
    if (sessionStorage.getItem("seeded")) return;
    sessionStorage.setItem("seeded", "1");
    const t = { id: "a".repeat(32), title: "기기 대화", created_at: "2026-10-09T00:00:00Z", updated_at: "2026-10-09T00:00:00Z", turns: [{ question: "기기 질문", answer: "기기 답", route: "rag", evidence_ids: [], at: "2026-10-09T00:00:00Z" }] };
    localStorage.setItem("ragdog:v1:threads", JSON.stringify([t]));
    localStorage.setItem("ragdog:v1:profile", JSON.stringify({ name: "두부" }));
  });
  await signIn(page);
  const account = await fakeAccount(page, [thread(1)]);
  await fakeApi(page, []);
  await page.goto("/chat");
  const offer = page.getByRole("region", { name: "기기 기록 옮기기" });
  await expect(offer).toContainText("로그인 전 기록이 2개");
  await offer.getByRole("button", { name: "계정으로 옮기기" }).click();
  await expect(offer).toHaveCount(0);
  expect(account.tables.ragdog_user_threads.map((r) => r.thread_id)).toContain("a".repeat(32));
  expect(account.tables.ragdog_user_profile[0]?.profile).toEqual({ name: "두부" });
  expect(await page.evaluate(() => [localStorage.getItem("ragdog:v1:threads"), localStorage.getItem("ragdog:v1:profile")])).toEqual([null, null]);
});

test("clearing while signed in deletes the account's rows; signing out shows only this browser", async ({ page }) => {
  page.on("dialog", (dialog) => dialog.accept());
  await signIn(page);
  const account = await fakeAccount(page, [thread(1), thread(2)], { name: "보리" });
  await fakeApi(page, []);
  await page.goto("/chat");
  await openList(page);
  await page.getByRole("button", { name: "계정의 기록 모두 지우기" }).filter({ visible: true }).click();
  await expect.poll(() => account.calls.filter((call) => call.method === "DELETE").map((call) => call.table)).toEqual(["ragdog_user_threads", "ragdog_user_profile"]);
  expect(account.tables).toEqual({ ragdog_user_threads: [], ragdog_user_profile: [] });

  account.tables.ragdog_user_threads.push(thread(3));
  await page.reload();
  await openList(page);
  await expect(page.getByRole("button", { name: "계정 대화 3" }).filter({ visible: true })).toBeVisible();
  await page.evaluate(() => sessionStorage.setItem("signed-out", "1"));
  await page.getByRole("button", { name: "로그아웃" }).click();
  await expect(page.getByRole("button", { name: "Google로 로그인" })).toBeVisible();
  await openList(page);
  await expect(page.getByText("이 브라우저에만 저장됩니다").filter({ visible: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "계정 대화 3" })).toHaveCount(0);
  expect(await page.evaluate((key) => localStorage.getItem(key), STORAGE_KEY)).toBeNull(); // the token is gone
});

test("deleting the account removes it and signs out, after a warning", async ({ page }) => {
  const dialogs: string[] = [];
  page.on("dialog", (dialog) => {
    dialogs.push(dialog.message());
    void dialog.accept();
  });
  await signIn(page);
  const account = await fakeAccount(page, [thread(1)], { name: "보리" });
  await fakeApi(page, []);
  await page.goto("/chat");
  await openList(page);
  await page.evaluate(() => sessionStorage.setItem("signed-out", "1"));
  await page.getByRole("button", { name: "계정 삭제" }).filter({ visible: true }).click();
  await expect(page.getByRole("status").filter({ hasText: "계정을 삭제했습니다" })).toBeVisible();
  expect(dialogs[0]).toContain("되돌릴 수 없습니다");
  expect(dialogs[0]).toContain("타사 연결");
  const call = account.calls.find((c) => c.table === "delete_my_account")!;
  expect(call.method).toBe("POST");
  expect(call.auth).toBe(`Bearer ${TOKEN}`);
  await expect(page.getByRole("button", { name: "Google로 로그인" })).toBeVisible();
  expect(await page.evaluate((key) => localStorage.getItem(key), STORAGE_KEY)).toBeNull();
});
