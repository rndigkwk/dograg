import { expect, test } from "@playwright/test";

import { fakeApi, result } from "./fake-api";

const ANSWER = result("펫보험 가입률은 2023년 11.9%에서 2025년 15.2%로 올랐습니다.", {
  route: "analysis",
  evidence_rows: [{ title: "2025 한국 반려동물 보고서", page: 74, excerpt: "펫보험 가입률 15.2%", source: "data/source/kb.pdf" }],
});

test("the report page sends questions straight to the reports and shows the page evidence", async ({ page }) => {
  const api = await fakeApi(page, [[["step", { message: "보고서에서 근거를 찾고 있습니다…" }], ["token", { text: "펫보험 " }], ANSWER]]);
  await page.goto("/reports");
  await expect(page.getByRole("region", { name: "보고서 목록" }).getByRole("button")).toHaveCount(5);

  // A suggested question that spans several reports, with no report chosen.
  await page.getByRole("button", { name: /^KB 2025 보고서와 복지실태 보고서에서/ }).click();
  const first = page.getByRole("article", { name: /^답변: KB 2025 보고서와 복지실태/ });
  await expect(first).toContainText("15.2%");
  await expect(first.getByText("근거 1 · 2025 한국 반려동물 보고서 · 페이지 74")).toBeVisible();
  expect(api.chats[0]).toMatchObject({ route: "report", history: [], profile: null, suggest_memory: false });

  // A chosen report names itself in the question.
  await page.getByRole("button", { name: /^2025 한국 반려동물 보고서/ }).click();
  await page.getByLabel("보고서에 물어볼 질문").fill("펫보험 가입률은?");
  await page.getByRole("button", { name: "묻기" }).click();
  await expect(page.getByRole("article", { name: "답변: KB 2025 한국 반려동물 보고서에서 펫보험 가입률은?" })).toBeVisible();
  expect(api.chats[1].question).toBe("KB 2025 한국 반려동물 보고서에서 펫보험 가입률은?");
});

test("the report page shows the question limit as a notice", async ({ page }) => {
  await fakeApi(page, [[["limited", { message: "오늘 질문 횟수를 다 썼습니다.", wait_minutes: 30 }]]]);
  await page.goto("/reports");
  await page.getByLabel("보고서에 물어볼 질문").fill("양육비는?");
  await page.getByRole("button", { name: "묻기" }).click();
  await expect(page.getByRole("article", { name: "답변: 양육비는?" }).getByRole("alert")).toHaveText("오늘 질문 횟수를 다 썼습니다.");
});
