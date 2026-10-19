import { describe, expect, it } from "vitest";

import { consultation, EXCERPT_PREVIEW_CHARS, guide, isGuide, reportPage } from "./evidence";

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
      scanned: false,
    });
  });

  it("marks text read from the page image", () => {
    expect(reportPage({ excerpt: "12.8%", page: 77, scanned: true }, 0).scanned).toBe(true);
    expect(reportPage({ excerpt: "12.8%", page: 77, scanned: "true" }, 0).scanned).toBe(false);
  });
});

describe("guide", () => {
  const row = { kind: "care_guide", title: "재난 대응 가이드라인", page: 2, organization: "동물사랑배움터",
    url: "https://apms.epis.or.kr/home/kor/board.do?idx=639", piece: "재난 키트를 만든다" };

  it("tells a care guide from a consultation", () => {
    expect(isGuide(row)).toBe(true);
    expect(isGuide({ "qa.output": "답변" })).toBe(false);
  });

  it("labels a care guide by its title and page, with its source and link", () => {
    expect(guide(row, 0)).toEqual({ title: "지침 1 · 재난 대응 가이드라인 · 2쪽", organization: "동물사랑배움터",
      excerpt: "재난 키트를 만든다", url: "https://apms.epis.or.kr/home/kor/board.do?idx=639" });
  });

  it("drops a link that is not https", () => {
    expect(guide({ ...row, url: "javascript:alert(1)" }, 0).url).toBe("");
  });
});
