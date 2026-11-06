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

  it("names pages in the guardian's words, not the feature's", () => {
    const labels = GROUPS.flatMap((group) => [group.label, ...group.pages.map((page) => page.label)]);
    for (const word of ["질병 문의", "찾기", "시설 찾기", "지역별 진료비", "보고서 질문"]) expect(labels).not.toContain(word);
  });

  it("finds a page's group, also below it, and none at home", () => {
    expect(groupOf("/fees")?.label).toBe("병원·비용");
    expect(groupOf("/visit-prep")?.label).toBe("상담");
    expect(groupOf("/")).toBeUndefined();
  });
});
