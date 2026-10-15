import { describe, expect, it } from "vitest";

import { applyEvent, finish, FIRST_STEP, historyOf, type Message, type Pending, startPending } from "./chat";
import type { StreamEvent } from "./sse";

function run(events: StreamEvent[]): { pending: Pending; memory?: unknown } {
  let pending = startPending();
  let memory;
  for (const event of events) {
    const next = applyEvent(pending, event);
    pending = next.pending;
    memory = next.memory ?? memory;
  }
  return { pending, memory };
}

describe("applyEvent", () => {
  it("shows steps until the first token, then the text", () => {
    const { pending } = run([
      { kind: "step", data: { message: "자료를 찾고 있습니다" } },
      { kind: "token", data: { text: "구토가 " } },
      { kind: "step", data: { message: "근거를 확인합니다" } },
      { kind: "token", data: { text: "계속되면" } },
    ]);
    expect(pending.step).toBe("자료를 찾고 있습니다");
    expect(pending.text).toBe("구토가 계속되면");
  });

  it("keeps the urgent warning and drops the repeated safety notice", () => {
    const { pending, memory } = run([
      { kind: "urgent", data: { notice: "지금 병원에 가세요", hospitals: { nearest: [] } } },
      { kind: "result", data: { answer: "답", route: "rag", abstained: false, trace_id: "t", safety_notice: "지금 병원에 가세요", memory: { upto: 0, summary: "" } } },
    ]);
    expect(pending.answer.urgent?.notice).toBe("지금 병원에 가세요");
    expect(pending.answer.safetyNotice).toBeNull();
    expect(pending.answer.content).toBe("답");
    expect(memory).toEqual({ upto: 0, summary: "" });
  });

  it("marks the question limit as a notice", () => {
    const { pending } = run([{ kind: "limited", data: { message: "한도", wait_minutes: 20 } }]);
    expect(finish(pending, "실패")).toMatchObject({ content: "한도", notice: "limited" });
  });
});

describe("finish", () => {
  it("keeps streamed text when the stream broke before the result", () => {
    const { pending } = run([{ kind: "token", data: { text: "부분" } }]);
    expect(finish(pending, "실패")).toMatchObject({ content: "부분", notice: "error" });
  });

  it("says it failed when nothing arrived", () => {
    expect(finish(startPending(), "실패")).toMatchObject({ content: "실패", notice: "error" });
    expect(startPending().step).toBe(FIRST_STEP);
  });
});

describe("historyOf", () => {
  it("sends answered turns only, the newest 40", () => {
    const messages: Message[] = [
      { role: "user", content: "q1" },
      { role: "assistant", content: "a1", route: "rag" },
      { role: "user", content: "q2" },
      { role: "assistant", content: "한도", notice: "limited" },
    ];
    expect(historyOf(messages)).toEqual([
      { role: "user", content: "q1" },
      { role: "assistant", content: "a1", route: "rag" },
    ]);
    const many: Message[] = Array.from({ length: 30 }, (_, i) => [
      { role: "user", content: `q${i}` } as Message,
      { role: "assistant", content: `a${i}` } as Message,
    ]).flat();
    expect(historyOf(many)).toHaveLength(40);
    expect(historyOf(many)[0]).toEqual({ role: "user", content: "q10" });
  });
});
