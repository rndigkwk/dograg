"use client";

import { useEffect, useRef, useState } from "react";

import { askChat, warmUp } from "@/lib/api";
import { type Answer, applyEvent, finish, FIRST_STEP, type Pending, startPending } from "@/lib/chat";
import { failureMessage } from "@/lib/failure";
import { CROSS_QUESTIONS, type Report, REPORTS, scoped } from "@/lib/reports";

import Evidence from "./Evidence";
import Feedback from "./Feedback";
import Markdown from "./Markdown";
import Waiting from "./Waiting";

const FAILED = "답변을 만들지 못했습니다. 잠시 뒤 다시 질문해 주세요.";
type Asked = { question: string; answer: Answer };

function ReportCard({ report, chosen, onChoose }: { report: Report; chosen: boolean; onChoose: () => void }) {
  return (
    <button
      type="button"
      onClick={onChoose}
      aria-pressed={chosen}
      className={`rounded-xl border bg-white p-3 text-left outline-none focus-visible:ring-2 focus-visible:ring-accent ${chosen ? "border-accent ring-1 ring-accent" : "border-line hover:border-accent/50"}`}
    >
      <span className="block font-semibold">{report.title}</span>
      <span className="mt-0.5 block text-xs text-muted">
        {report.publisher} · {report.published} · {report.pages}쪽
      </span>
      <span className="mt-1 block text-sm">{report.covers}</span>
    </button>
  );
}

/** The report page: the five PDF reports as cards, suggested questions, and answers that go straight to
 * the report search (api/chat.py route "report", no classification call) with their page evidence. */
export default function ReportAsk() {
  const [chosen, setChosen] = useState<Report | null>(null);
  const [draft, setDraft] = useState("");
  const [asked, setAsked] = useState<Asked[]>([]);
  const [pending, setPending] = useState<{ question: string; state: Pending } | null>(null);
  const controller = useRef<AbortController | null>(null);

  useEffect(() => {
    warmUp();
    return () => controller.current?.abort();
  }, []);

  async function ask(text: string) {
    const question = scoped(text, chosen);
    if (!question || pending) return;
    let state = startPending();
    setPending({ question, state });
    controller.current = new AbortController();
    try {
      const request = { question, history: [], memory: { upto: 0, summary: "" }, profile: null, location: null, suggest_memory: false, declined_memory: [], route: "report" as const };
      for await (const event of askChat(request, controller.current.signal)) {
        state = applyEvent(state, event).pending;
        setPending({ question, state });
      }
    } catch (error) {
      if ((error as Error).name === "AbortError") return;
      setAsked((shown) => [{ question, answer: finish(state, failureMessage(error, FAILED)) }, ...shown]);
      setPending(null);
      return;
    }
    setAsked((shown) => [{ question, answer: finish(state, FAILED) }, ...shown]);
    setPending(null);
  }

  function submit(event: React.FormEvent) {
    event.preventDefault();
    const text = draft.trim();
    if (!text) return;
    setDraft("");
    void ask(text);
  }

  const suggestions = chosen ? chosen.questions : CROSS_QUESTIONS;
  return (
    <div className="space-y-5">
      <section aria-label="보고서 목록">
        <h2 className="mb-2 font-bold">보고서 5종</h2>
        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {REPORTS.map((report) => (
            <ReportCard key={report.id} report={report} chosen={chosen?.id === report.id} onChoose={() => setChosen(chosen?.id === report.id ? null : report)} />
          ))}
        </div>
        <p className="mt-2 text-sm text-muted">
          {chosen ? `「${chosen.title}」에서 찾습니다. 카드를 다시 누르면 5종 전체에서 찾습니다.` : "카드를 고르면 그 보고서에서, 고르지 않으면 5종 전체에서 찾습니다."}
        </p>
      </section>

      <section aria-label="질문하기" className="rounded-xl border border-line bg-white p-4">
        <p className="mb-2 text-sm font-semibold">{chosen ? "이 보고서에 물어보기 좋은 질문" : "여러 보고서를 함께 보는 질문"}</p>
        <div className="mb-3 flex flex-wrap gap-2">
          {suggestions.map((question) => (
            <button
              key={question}
              type="button"
              disabled={Boolean(pending)}
              onClick={() => void ask(question)}
              className="rounded-full border border-accent/40 bg-accent/5 px-3 py-1.5 text-left text-sm text-accent hover:bg-accent/10 disabled:opacity-50"
            >
              {question}
            </button>
          ))}
        </div>
        <form onSubmit={submit} className="flex gap-2">
          <label htmlFor="report-question" className="sr-only">
            보고서에 물어볼 질문
          </label>
          <input
            id="report-question"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            maxLength={500}
            placeholder={chosen ? `${chosen.title}에 물어볼 것` : "예: 반려동물 월평균 양육비는 얼마인가요?"}
            className="min-w-0 flex-1 rounded-lg border border-line px-3 py-2"
          />
          <button type="submit" disabled={!draft.trim() || Boolean(pending)} className="shrink-0 rounded-lg bg-accent px-4 py-2 font-semibold text-white disabled:opacity-50">
            묻기
          </button>
        </form>
        <p className="mt-2 text-xs text-muted">보고서에 있는 내용만 근거로 답하고, 근거 쪽수를 함께 보여 줍니다. 질문은 채팅과 같은 하루 질문 횟수에 포함됩니다.</p>
      </section>

      {pending ? (
        <article aria-busy="true" aria-label="답변을 만드는 중" className="rounded-xl border border-line bg-white p-4">
          <p className="font-semibold">Q. {pending.question}</p>
          {pending.state.text ? (
            <Markdown text={pending.state.text} />
          ) : (
            <div className="mt-2">
              <Waiting text={pending.state.step} started={pending.state.step !== FIRST_STEP} />
            </div>
          )}
        </article>
      ) : null}
      {asked.map(({ question, answer }, index) => (
        <article key={asked.length - index} aria-label={`답변: ${question}`} className="rounded-xl border border-line bg-white p-4">
          <p className="mb-2 font-semibold">Q. {question}</p>
          {answer.notice ? <p role="alert" className="rounded-lg bg-warn/10 p-3">{answer.content}</p> : <Markdown text={answer.content} />}
          <Evidence route={answer.route} rows={answer.evidenceRows ?? []} />
          <Feedback answer={answer} question={question} />
        </article>
      ))}
    </div>
  );
}
