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

test("a date set with the vet wins over the guide, and the schedule downloads as a calendar file", async ({ page }) => {
  await page.clock.setFixedTime(new Date("2026-10-27T10:00:00"));
  await page.goto("/care");
  const download = page.getByRole("button", { name: "캘린더 파일(.ics)로 받기" });
  await expect(download).toBeDisabled();

  const rabies = page.getByRole("listitem").filter({ hasText: "광견병 추가접종" });
  await rabies.getByLabel("광견병 추가접종 마지막으로 한 날").fill("2025-11-20");
  await expect(rabies.getByText("다음: 2026-11-20 (지침으로 계산한 날)")).toBeVisible();
  await rabies.getByLabel("광견병 추가접종 수의사와 정한 다음 날").fill("2026-12-05");
  await expect(rabies.getByText("다음: 2026-12-05 (수의사와 정한 날)")).toBeVisible();
  await page.reload();
  await expect(page.getByLabel("광견병 추가접종 수의사와 정한 다음 날")).toHaveValue("2026-12-05");

  const saving = page.waitForEvent("download");
  await download.click();
  const file = await saving;
  expect(file.suggestedFilename()).toBe("ragdog-care.ics");
  const text = (await (await file.createReadStream()).toArray()).join("").replace(/\r\n /g, "");
  expect(text).toContain("DTSTART;VALUE=DATE:20261205");
  expect(text).toContain("SUMMARY:광견병 추가접종");
  await expect(page.getByText("1개 일정을 담았습니다.")).toBeVisible();
});

test("the menu leads to the care schedule", async ({ page }) => {
  await page.goto("/");
  await openFromMenu(page, "우리 아이", "관리 일정");
  await expect(page).toHaveURL(/\/care$/);
});
