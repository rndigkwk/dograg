import { describe, expect, it } from "vitest";

import { consultation, EXCERPT_PREVIEW_CHARS, reportPage } from "./evidence";

describe("consultation", () => {
  it("labels a consultation by its metadata, with dashes for what is missing", () => {
    expect(consultation({ "meta.lifeCycle": "성견", "meta.disease": "장염", "qa.output": "수액 치료를 합니다" }, 0)).toEqual({
      title: "1. 성견 / - / 장염",
      answer: "수액 치료를 합니다",
    });
  });
});

describe("reportPage", () => {
  it("shortens long excerpts to one line", () => {
    const row = { title: "펫로스 보고서", page: 12, excerpt: "가".repeat(200) + "\n\n끝" };
    const got = reportPage(row, 1);
    expect(got.title).toBe("근거 2 · 펫로스 보고서 · 페이지 12");
    expect(got.preview).toHaveLength(EXCERPT_PREVIEW_CHARS + 1);
    expect(got.preview.endsWith("…")).toBe(true);
    expect(got.excerpt).toBe(row.excerpt);
  });

  it("names the default report and an unknown page", () => {
    expect(reportPage({ excerpt: "짧은  글\n줄" }, 0)).toEqual({
      title: "근거 1 · 2025 한국 반려동물 보고서 · 페이지 확인 불가",
      preview: "짧은 글 줄",
      excerpt: "짧은  글\n줄",
    });
  });
});
