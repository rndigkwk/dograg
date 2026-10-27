import { describe, expect, it } from "vitest";

import type { StreamEvent } from "./sse";
import type { Message } from "./chat";
import { applyVisitEvent, consultationFrom, emptyRun, MAX_CONSULTATION_CHARS, outcomeLine, type Report } from "./visitPrep";

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
    expect(outcomeLine({ ...report, claims: 11 })).toBe("검수 통과 · 주장 11개 모두 근거 확인 · 다시 쓰기 1회 · 42초");
    expect(outcomeLine({ ...report, passed: false, status: "검수 미통과" })).toContain("수의사(사람)의 확인이 필요한 초안");
  });
});

describe("consultationFrom", () => {
  const ask = (content: string): Message => ({ role: "user", content });
  const reply = (route: string, notice?: "error"): Message => ({ role: "assistant", content: "답", route, ...(notice ? { notice } : {}) }) as Message;

  it("carries every health question up to this answer, oldest first, and no answer", () => {
    // The review's two turns (2026-10-27): the first one's "어제부터" was lost.
    const messages = [
      ask("강아지가 어제부터 설사를 해요."), reply("rag"),
      ask("마포구 동물병원 알려줘"), reply("sql"),
      ask("5살이고 7kg입니다. 오늘은 두 번 설사했고 구토는 없어요."), reply("rag"),
      ask("나중 질문"), reply("rag"),
    ];
    expect(consultationFrom(messages, 5)).toEqual({
      text: "강아지가 어제부터 설사를 해요.\n5살이고 7kg입니다. 오늘은 두 번 설사했고 구토는 없어요.", cut: false });
  });

  it("leaves out a question whose answer failed", () => {
    expect(consultationFrom([ask("앞 질문"), reply("rag", "error"), ask("설사해요"), reply("rag")], 3).text).toBe("설사해요");
  });

  it("says when the conversation does not fit", () => {
    const long = "가".repeat(300);
    const got = consultationFrom([ask(long), reply("rag"), ask(long), reply("rag")], 3);
    expect(got.cut).toBe(true);
    expect(got.text).toHaveLength(MAX_CONSULTATION_CHARS);
  });
});
