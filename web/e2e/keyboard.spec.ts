import { expect, test } from "@playwright/test";

import { ask, fakeApi, result } from "./fake-api";

// The keyboard pass (2026-10-24): every page usable with Tab, Enter, arrows and Escape alone.

test("the first Tab offers a skip past the menu to the page", async ({ page }) => {
  await fakeApi(page, []);
  await page.goto("/fees");
  await page.keyboard.press("Tab");
  const skip = page.getByRole("link", { name: "본문으로 건너뛰기" });
  await expect(skip).toBeFocused();
  await expect(skip).toBeVisible();
  await page.keyboard.press("Enter");
  await expect(page.locator("main")).toBeFocused();
});

test("a menu group opens, walks and closes from the keyboard", async ({ page, isMobile }) => {
  test.skip(isMobile, "the group menus are the wide-screen bar; phones have bottom tabs");
  await fakeApi(page, []);
  await page.goto("/");
  const menu = page.getByRole("navigation", { name: "메뉴" });
  const group = menu.getByRole("button", { name: "상담" });
  await group.focus();
  await page.keyboard.press("Enter");
  await expect(group).toHaveAttribute("aria-expanded", "true");
  await page.keyboard.press("Tab");
  await expect(menu.getByRole("link", { name: "질병 문의" })).toBeFocused();

  // Escape closes the list and puts the focus back on its button.
  await page.keyboard.press("Escape");
  await expect(group).toHaveAttribute("aria-expanded", "false");
  await expect(group).toBeFocused();

  // Tab past the last page closes the list too.
  await page.keyboard.press("Enter");
  for (let i = 0; i < 4; i++) await page.keyboard.press("Tab");
  await expect(menu.getByRole("button", { name: "찾기" })).toBeFocused();
  await expect(group).toHaveAttribute("aria-expanded", "false");
});

test("the data tabs move with the arrow keys and keep one Tab stop", async ({ page }) => {
  await fakeApi(page, [], {
    "/stats/overview": { diseases: [{ label: "장염", count: 3 }], departments: [{ label: "내과", count: 5 }], hospitals_by_province: [], place_sources: [] },
  });
  await page.goto("/data");
  const tabs = page.getByRole("tab");
  await expect(tabs.first()).toHaveAttribute("tabindex", "0");
  await expect(tabs.nth(1)).toHaveAttribute("tabindex", "-1");
  await tabs.first().focus();
  await page.keyboard.press("ArrowRight");
  await expect(tabs.nth(1)).toBeFocused();
  await expect(tabs.nth(1)).toHaveAttribute("aria-selected", "true");
  await page.keyboard.press("ArrowLeft");
  await page.keyboard.press("ArrowLeft"); // wraps to the last tab
  await expect(tabs.last()).toBeFocused();
});

test("after an answer to a question sent with Enter, the box has the focus again", async ({ page }) => {
  await fakeApi(page, [[["token", { text: "물을 조금씩 주세요." }], result("물을 조금씩 주세요.")]]);
  await page.goto("/chat");
  await ask(page, "강아지가 물을 안 마셔요");
  await expect(page.getByLabel("대화", { exact: true }).getByText("물을 조금씩 주세요.").first()).toBeVisible();
  await expect(page.getByRole("textbox", { name: "질문" })).toBeFocused();
});

test("a visit-prep report moves the focus to what comes next: the answer box, then the report", async ({ page }) => {
  const report = { report: "# 방문 준비 보고서\n\n- 설사가 이틀째입니다.", passed: true, status: "검수 통과", round: 1, steps: [], urgent: false, seconds: 42, answered: true };
  await fakeApi(page, [], {}, {
    "/visit-prep": [["paused", { thread_id: "t1", questions: ["언제부터였나요?"] }]],
    "/visit-prep/t1/answer": [["result", report]],
  });
  await page.goto("/visit-prep");
  await page.getByLabel("상담 내용").fill("말티즈가 이틀째 설사를 해요");
  await page.getByRole("button", { name: /방문 준비 보고서 만들기/ }).press("Enter");
  const answer = page.getByRole("region", { name: "보호자 질문" }).getByLabel(/답변/);
  await expect(answer).toBeFocused();
  await page.keyboard.type("어제 저녁부터요");
  await page.keyboard.press("Tab");
  await page.keyboard.press("Enter"); // 답하고 보고서 만들기
  await expect(page.getByRole("region", { name: "방문 준비 보고서" })).toBeFocused();
});

test("on the places page the kind pills show the focus and a search keeps it on 조회", async ({ page }) => {
  const source = { title: "행정안전부 동물병원 인허가 정보", url: "https://www.data.go.kr", rows: 2, updated: "2026-08-11 22:02:01" };
  const place = { id: "hospital-1", kind: "hospital", name: "강남동물병원1", address: "서울특별시 강남구 테헤란로 1", phone: null, homepage: null, category: null, latitude: 37.5, longitude: 127.03, info: {}, info_lines: [] };
  await fakeApi(page, [], {
    "/places/kinds": [
      { kind: "hospital", label: "동물병원", has_location: true, source },
      { kind: "funeral", label: "장묘업체", has_location: false, source: null },
    ],
    "/places/regions": { 서울특별시: ["강남구"] },
    "/places/search": { total: 1, places: [place] },
  });
  await page.goto("/places");
  const radio = page.getByRole("radio", { name: "동물병원" });
  await radio.focus();
  await page.keyboard.press("ArrowRight"); // radios move with the arrows
  const pill = page.locator("label", { has: page.getByRole("radio", { name: "장묘업체" }) });
  await expect(page.getByRole("radio", { name: "장묘업체" })).toBeChecked();
  await expect(pill).toHaveCSS("outline-style", "solid");

  await page.keyboard.press("ArrowLeft");
  const go = page.getByRole("button", { name: "조회" });
  await go.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("status")).toContainText("1곳을 찾았습니다");
  await expect(go).toBeFocused();
});
