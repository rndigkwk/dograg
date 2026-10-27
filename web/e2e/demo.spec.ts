import { expect, test } from "@playwright/test";

import { FAKE_API } from "../playwright.config";

// The sample page (src/app/demo): saved answers and a saved report, shown without the API.
test("the sample shows an answer with its case, a declined question and a report, and asks the API nothing", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("link", { name: /예시로 2분 둘러보기/ }).click();
  await expect(page).toHaveURL(/\/demo$/);

  // Counted from a fresh load of the sample, not the home page before it.
  const asked: string[] = [];
  page.on("request", (request) => {
    if (request.url().startsWith(FAKE_API)) asked.push(request.url());
  });
  await page.reload();
  await expect(page.getByRole("note").filter({ hasText: "예시 화면입니다" })).toBeVisible();

  await page.getByRole("link", { name: "사례 1" }).click();
  await expect(page.getByText("11년 동안 강아지를 기르고 있습니다", { exact: false }).first()).toBeVisible();

  await expect(page.getByText("답할 근거를 찾지 못해", { exact: false })).toBeVisible();
  await expect(page.getByRole("heading", { name: "방문 준비 보고서" })).toBeVisible();
  await expect(page.getByRole("link", { name: "상담하기" })).toHaveAttribute("href", "/chat");
  expect(asked).toEqual([]);
});
