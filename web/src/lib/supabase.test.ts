import { describe, expect, it } from "vitest";

import { safeReturnPath } from "./supabase";

describe("safeReturnPath", () => {
  it("keeps this site's own paths", () => {
    expect(safeReturnPath("/chat")).toBe("/chat");
    expect(safeReturnPath("/places?id=hospital-1")).toBe("/places?id=hospital-1");
  });

  it("never sends the browser to another site or back to the callback", () => {
    for (const bad of [null, "", "https://evil.example", "//evil.example", "/\\evil.example", "javascript:alert(1)", "/auth/callback"]) {
      expect(safeReturnPath(bad)).toBe("/");
    }
  });
});
