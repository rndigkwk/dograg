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
