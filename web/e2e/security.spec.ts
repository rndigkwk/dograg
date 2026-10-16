import { expect, test } from "@playwright/test";

import { FAKE_API } from "../playwright.config";
import { fakeApi } from "./fake-api";

test("every page is sent with the security headers", async ({ request }) => {
  for (const path of ["/", "/chat", "/places", "/data", "/visit-prep"]) {
    const headers = (await request.get(path)).headers();
    expect(headers["x-frame-options"]).toBe("DENY");
    expect(headers["x-content-type-options"]).toBe("nosniff");
    expect(headers["referrer-policy"]).toBe("strict-origin-when-cross-origin");
    expect(headers["x-powered-by"]).toBeUndefined();
    const csp = headers["content-security-policy"];
    expect(csp).toContain("frame-ancestors 'none'");
    expect(csp).toContain(`connect-src 'self' ${FAKE_API}`);
    expect(csp).not.toContain("unsafe-eval"); // production build
  }
});

test("the pages work under the policy (no blocked requests)", async ({ page }) => {
  const blocked: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error" && /Content Security Policy/i.test(message.text())) blocked.push(message.text());
  });
  await fakeApi(page, [], { "/places/kinds": [], "/places/regions": {} });
  for (const path of ["/", "/chat", "/places"]) {
    await page.goto(path);
    await page.waitForLoadState("networkidle");
  }
  expect(blocked).toEqual([]);
});
