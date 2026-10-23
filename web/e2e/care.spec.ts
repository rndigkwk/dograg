import { expect, test } from "@playwright/test";
import { openFromMenu } from "./nav";

// The care schedule (web/src/lib/careSchedule.ts): no API, the dates stay in this browser.
test("a last-done date gives the next date from the guide, and it stays after a reload", async ({ page }) => {
  await page.clock.setFixedTime(new Date("2026-10-19T10:00:00"));
  await page.goto("/care");
  await expect(page.getByRole("heading", { name: "관리 일정" })).toBeVisible();

  const heartworm = page.getByRole("listitem").filter({ hasText: "심장사상충 예방약" });
  await heartworm.getByLabel("심장사상충 예방약 마지막으로 한 날").fill("2026-09-10");
  await expect(heartworm.getByText("다음: 2026-10-10")).toBeVisible();
  await expect(heartworm.getByText("지났어요")).toBeVisible();

  const deworming = page.getByRole("listitem").filter({ hasText: "내부 기생충 구충제" });
  await deworming.getByLabel("내부 기생충 구충제 마지막으로 한 날").fill("2026-08-01");
  await expect(deworming.getByText("다음: 2026-11-01 ~ 2027-02-01")).toBeVisible();
  await expect(deworming.getByText("13일 남음")).toBeVisible();

  await page.reload();
  await expect(page.getByLabel("심장사상충 예방약 마지막으로 한 날")).toHaveValue("2026-09-10");
  await expect(page.getByRole("link", { name: "원문 보기" })).toHaveAttribute("href", /apms\.epis\.or\.kr.*idx=1454/);

  await page.getByLabel("심장사상충 예방약 마지막으로 한 날").fill("");
  await page.reload();
  await expect(page.getByLabel("심장사상충 예방약 마지막으로 한 날")).toHaveValue("");
});

test("the menu leads to the care schedule", async ({ page }) => {
  await page.goto("/");
  await openFromMenu(page, "우리 아이", "관리 일정");
  await expect(page).toHaveURL(/\/care$/);
});
