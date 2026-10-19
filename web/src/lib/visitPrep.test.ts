import { describe, expect, it } from "vitest";

import type { StreamEvent } from "./sse";
import { applyVisitEvent, emptyRun, outcomeLine, type Report } from "./visitPrep";

const run = (events: StreamEvent[]) => events.reduce(applyVisitEvent, emptyRun());
const report: Report = { report: "# 보고서", passed: true, status: "검수 통과", round: 1, steps: [], urgent: false, seconds: 42, answered: false };

describe("applyVisitEvent", () => {
  it("collects steps and pauses with the questions", () => {
    const got = run([
      { kind: "urgent", data: { notice: "응급" } },
      { kind: "step", data: { line: "검색 자료를 준비했습니다" } },
      { kind: "step", data: { line: "증상을 조사했습니다" } },
      { kind: "paused", data: { thread_id: "t1", questions: ["언제부터였나요?"] } },
    ]);
    expect(got).toMatchObject({ urgent: true, steps: ["검색 자료를 준비했습니다", "증상을 조사했습니다"], paused: { threadId: "t1", questions: ["언제부터였나요?"] } });
  });

  it("ends with the report, or with a refusal", () => {
    expect(run([{ kind: "result", data: report }]).result).toEqual(report);
    expect(run([{ kind: "busy", data: { message: "다른 사용자의 보고서를 만드는 중입니다." } }]).notice).toEqual({ kind: "busy", message: "다른 사용자의 보고서를 만드는 중입니다." });
    expect(run([{ kind: "limited", data: { message: "하루 2번", wait_minutes: null } }]).notice?.kind).toBe("limited");
  });

  it("an error with a thread id can go on; one without cannot", () => {
    const stopped = run([{ kind: "step", data: { line: "증상을 조사했습니다" } }, { kind: "error", data: { message: "멈췄습니다", thread_id: "t9" } }]);
    expect(stopped).toMatchObject({ retry: { threadId: "t9" }, notice: { kind: "error", message: "멈췄습니다" }, steps: ["증상을 조사했습니다"] });
    expect(run([{ kind: "error", data: { message: "실패" } }]).retry).toBeNull();
  });
});

describe("outcomeLine", () => {
  it("names the review result", () => {
    expect(outcomeLine({ ...report, answered: true })).toBe("검수 통과 · 다시 쓰기 1회 · 42초 · 보호자 답변 반영");
    expect(outcomeLine({ ...report, passed: false, status: "검수 미통과" })).toContain("수의사(사람)의 확인이 필요한 초안");
  });
});
