// The visit-prep report (api/visit_prep.py): one streamed run that may pause to ask the guardian,
// then resume with the answer. Pure state, tested in visitPrep.test.ts.

import type { StreamEvent } from "./sse";

export const MAX_CONSULTATION_CHARS = 500; // src/visit_prep_runs.py
export const MAX_ANSWER_CHARS = 300; // team/core/config.py
export const PASSED = "검수 통과"; // team/core/config.py
export const URGENT = "응급 징후가 의심됩니다. 보고서를 기다리지 말고 지금 가까운 동물병원에 연락하세요.";
export const EXPIRED = "질문을 받은 지 30분이 지나 답변 대기가 끝났습니다. 다시 만들어 주세요.";
// A consultation carried from the chat ("이 상담으로 방문 준비 보고서 만들기"): in sessionStorage,
// not in the URL, so the text stays out of browser history and server logs.
export const HANDOFF_KEY = "ragdog:v1:visit_prep_consultation";

export type Report = {
  report: string;
  passed: boolean;
  status: string;
  round: number;
  steps: string[];
  urgent: boolean;
  seconds: number;
  answered: boolean;
};

export type Run = {
  steps: string[];
  urgent: boolean;
  paused: { threadId: string; questions: string[] } | null;
  // A run that stopped on an error and may go on from its last finished step (api/visit_prep.py retry).
  retry: { threadId: string } | null;
  result: Report | null;
  // busy (another report is running), limited (question or report limit), error: shown as is
  notice: { kind: "busy" | "limited" | "error"; message: string } | null;
};

export const emptyRun = (): Run => ({ steps: [], urgent: false, paused: null, retry: null, result: null, notice: null });

export function applyVisitEvent(run: Run, { kind, data }: StreamEvent): Run {
  const d = data as Record<string, unknown>;
  switch (kind) {
    case "urgent":
      return { ...run, urgent: true };
    case "step":
      return { ...run, steps: [...run.steps, String(d.line ?? "")] };
    case "paused":
      return { ...run, paused: { threadId: String(d.thread_id), questions: (d.questions as string[]) ?? [] } };
    case "result":
      return { ...run, paused: null, result: d as unknown as Report };
    case "error":
      return { ...run, retry: d.thread_id ? { threadId: String(d.thread_id) } : null, notice: { kind, message: String(d.message ?? "") } };
    case "busy":
    case "limited":
      return { ...run, notice: { kind, message: String(d.message ?? "") } };
    default:
      return run;
  }
}

/** What the report's outcome line says (app_pages/visit_prep.py render_result). */
export function outcomeLine(report: Report): string {
  if (report.passed) return `검수 통과 · 다시 쓰기 ${report.round}회 · ${report.seconds}초${report.answered ? " · 보호자 답변 반영" : ""}`;
  if (report.status === "필수 조사 실패: 수의사(사람) 확인 필요")
    return "비슷한 상담 사례 조사가 오류로 실패해 보고서를 쓰지 않았습니다. 잠시 뒤 다시 시도하거나 병원에 바로 문의하세요.";
  if (report.status === "같은 지적 반복: 수의사(사람) 확인 필요")
    return "다시 써도 같은 문장이 근거 없음으로 지적돼, 수의사(사람)의 확인이 필요한 초안으로 표시했습니다.";
  return "두 번 고쳐도 근거를 확인하지 못한 문장이 있어, 수의사(사람)의 확인이 필요한 초안으로 표시했습니다.";
}
