import type { Page } from "@playwright/test";

/** Goes to a page through the menu as a guardian would: on a phone the group's bottom tab, then the
 * group's tab row; on a wide screen the group's menu in the top bar (components/NavBar.tsx). */
export async function openFromMenu(page: Page, group: string, label: string) {
  const phone = (page.viewportSize()?.width ?? 1280) < 768;
  if (phone) {
    await page.getByRole("navigation", { name: "하단 메뉴" }).getByRole("link", { name: group }).click();
    const row = page.getByRole("navigation", { name: `${group} 메뉴` }).getByRole("link", { name: label });
    if ((await row.getAttribute("aria-current")) !== "page") await row.click();
  } else {
    await page.getByRole("navigation", { name: "메뉴" }).getByRole("button", { name: group }).click();
    await page.getByRole("navigation", { name: "메뉴" }).getByRole("link", { name: label }).click();
  }
}
