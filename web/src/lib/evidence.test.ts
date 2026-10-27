import { describe, expect, it } from "vitest";

import { CASE_TITLE_CHARS, consultation, EXCERPT_PREVIEW_CHARS, guide, isGuide, linkCitations, reportPage } from "./evidence";

describe("consultation", () => {
  it("is titled by the other guardian's question, the labels kept second", () => {
    const question = "저희 강아지가 어제부터   설사를 하고 밥을 잘 안 먹어요. 열은 없는 것 같은데 병원에 가야 할까요? 그리고 사료를 바꿔야 하나요?";
    const got = consultation({ "meta.lifeCycle": "노령견", "meta.department": "내과", "meta.disease": "골절", question, "qa.output": "수액" }, 1);
    expect(got.title).toBe(`사례 2 · ${question.replace(/\s+/g, " ").slice(0, CASE_TITLE_CHARS).trimEnd()}…`);
    expect(got).toMatchObject({ labels: "노령견 / 내과 / 골절", question, answer: "수액" });
  });

  it("keeps the labels as the title for a row saved before the question was sent, with dashes for what is missing", () => {
    expect(consultation({ "meta.lifeCycle": "성견", "meta.disease": "장염", "qa.output": "수액 치료를 합니다" }, 0)).toEqual({
      title: "사례 1 · 성견 / - / 장염",
      labels: "성견 / - / 장염",
      question: "",
      answer: "수액 치료를 합니다",
    });
  });
});

describe("linkCitations", () => {
  it("links each cited number to its card, the brackets kept as text", () => {
    expect(linkCitations("설사가 계속되면 병원에 가세요. [사례 1] 물을 주세요 [사례 2, 3][지침 1]"))
      .toBe("설사가 계속되면 병원에 가세요. \\[[사례 1](#cite-case-1)\\] 물을 주세요 \\[[사례 2](#cite-case-2), [3](#cite-case-3)\\]\\[[지침 1](#cite-guide-1)\\]");
    expect(linkCitations("인용 없음")).toBe("인용 없음");
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
