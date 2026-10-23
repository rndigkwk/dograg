import { describe, expect, it } from "vitest";

import { GROUPS, groupOf } from "./nav";

describe("the menu", () => {
  it("keeps every page of the old menu, each in one group", () => {
    const hrefs = GROUPS.flatMap((group) => group.pages.map((page) => page.href));
    expect(new Set(hrefs).size).toBe(hrefs.length);
    for (const href of ["/data", "/chat", "/places", "/fees", "/visit-prep", "/care", "/reports", "/memory"]) {
      expect(hrefs).toContain(href);
    }
  });

  it("finds a page's group, also below it, and none at home", () => {
    expect(groupOf("/fees")?.label).toBe("찾기");
    expect(groupOf("/visit-prep")?.label).toBe("상담");
    expect(groupOf("/")).toBeUndefined();
  });
});
