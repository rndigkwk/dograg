import { describe, expect, it } from "vitest";

import { CROSS_QUESTIONS, REPORTS, scoped } from "./reports";

describe("reports", () => {
  it("lists the five reports, each with a question", () => {
    expect(REPORTS).toHaveLength(5);
    expect(new Set(REPORTS.map((r) => r.id)).size).toBe(5);
    for (const report of REPORTS) expect(report.questions.length).toBeGreaterThan(0);
    expect(CROSS_QUESTIONS).toHaveLength(3);
  });

  it("names the chosen report in the question, once", () => {
    const kb = REPORTS[0];
    expect(scoped(" 펫보험 가입률은? ", null)).toBe("펫보험 가입률은?");
    expect(scoped("펫보험 가입률은?", kb)).toBe("KB 2025 한국 반려동물 보고서에서 펫보험 가입률은?");
    expect(scoped("2025 한국 반려동물 보고서의 펫보험 가입률은?", kb)).toBe("2025 한국 반려동물 보고서의 펫보험 가입률은?");
  });
});
