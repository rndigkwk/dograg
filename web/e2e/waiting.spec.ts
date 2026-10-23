import { expect, type Page, test } from "@playwright/test";

import { FAKE_API } from "../playwright.config";
import { ask, result, sse } from "./fake-api";

const conversation = (page: Page) => page.getByLabel("대화", { exact: true });
const cors = { "Access-Control-Allow-Origin": "*", "Access-Control-Allow-Headers": "*" };

/** /chat answers with each of `replies` in turn: an HTTP status, "hang" (never answers) or an answer. */
async function chatReplies(page: Page, replies: (number | "hang" | string)[]) {
  const questions: string[] = [];
  await page.route(`${FAKE_API}/**`, async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (request.method() === "OPTIONS") return route.fulfill({ status: 204, headers: cors });
    if (path !== "/chat") return route.fulfill({ json: { status: "ok" }, headers: cors });
    questions.push(request.postDataJSON().question);
    const reply = replies[Math.min(questions.length - 1, replies.length - 1)];
    if (reply === "hang") return new Promise<void>(() => {}); // the browser gives up when the guardian stops
    if (typeof reply === "number") return route.fulfill({ status: reply, json: { detail: "down" }, headers: cors });
    return route.fulfill({ body: sse([result(reply)]), headers: { ...cors, "Content-Type": "text/event-stream" } });
  });
  return questions;
}

test("a failed answer says the server failed and sends the same question again", async ({ page }) => {
  const questions = await chatReplies(page, [503, "다시 받은 답입니다."]);
  await page.goto("/chat");
  await ask(page, "강아지가 기침을 해요");
  await expect(page.getByRole("alert").filter({ hasText: "서버에 잠시 문제가 생겼습니다" })).toBeVisible();

  await page.getByRole("button", { name: "같은 질문 다시 보내기" }).click();
  await expect(conversation(page).getByText("다시 받은 답입니다.")).toBeVisible();
  await expect(page.getByText("서버에 잠시 문제가 생겼습니다")).toHaveCount(0); // the failed try is replaced, not kept
  await expect(conversation(page).getByText("강아지가 기침을 해요")).toHaveCount(1);
  expect(questions).toEqual(["강아지가 기침을 해요", "강아지가 기침을 해요"]);
});

test("a long wait counts the seconds and can be stopped", async ({ page }) => {
  await chatReplies(page, ["hang"]);
  await page.goto("/chat");
  await ask(page, "강아지가 밥을 안 먹어요");
  await expect(page.getByRole("status").filter({ hasText: /\(\d+초\)/ })).toBeVisible({ timeout: 6000 });

  await page.getByRole("button", { name: "멈추기" }).click();
  await expect(conversation(page).getByText("답변을 멈췄습니다.")).toBeVisible();
  await expect(page.getByRole("button", { name: "같은 질문 다시 보내기" })).toBeVisible();
  await expect(page.getByRole("textbox", { name: "질문" })).toBeEnabled();
});
