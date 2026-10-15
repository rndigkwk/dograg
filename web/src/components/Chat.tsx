"use client";

import { useEffect, useRef, useState } from "react";

import { askChat, type Memory, warmUp } from "@/lib/api";
import { type Answer, applyEvent, type Emergency, finish, type Hospital, historyOf, type Message, type Pending, startPending } from "@/lib/chat";

import Evidence from "./Evidence";
import Feedback from "./Feedback";
import Markdown from "./Markdown";

const FAILED = "답변을 받지 못했습니다. 잠시 뒤 다시 질문해 주세요.";
const PLACEHOLDER = "예: 강아지가 계속 구토해요 / 강남구 병원을 알려주세요.";

function HospitalLine({ row }: { row: Hospital }) {
  const digits = row.phone?.replace(/\D/g, "");
  return (
    <li>
      <strong>{row.name}</strong> · {row.distance_km.toFixed(1)}km ·{" "}
      {digits ? <a href={`tel:${digits}`}>{row.phone}</a> : "전화번호 없음"}
      <div className="text-sm text-muted">{row.road_address || row.lot_address || ""}</div>
    </li>
  );
}

function UrgentBox({ notice, hospitals }: { notice: string; hospitals: Emergency }) {
  return (
    <div role="alert" className="mb-3 rounded-lg border border-danger/40 bg-danger/5 p-3">
      <p className="font-semibold text-danger">{notice}</p>
      <p className="mt-2 font-semibold">🚨 가까운 동물병원</p>
      {hospitals.nearest?.length ? (
        <>
          <ul className="mt-1 space-y-1">{hospitals.nearest.map((row) => <HospitalLine key={row.name} row={row} />)}</ul>
          {hospitals.night?.length ? (
            <>
              <p className="mt-2">이름에 24시·응급·야간이 들어간 가까운 병원</p>
              <ul className="mt-1 space-y-1">{hospitals.night.map((row) => <HospitalLine key={row.name} row={row} />)}</ul>
            </>
          ) : null}
          <p className="mt-2 text-sm text-muted">거리는 직선거리입니다. 영업 여부와 진료 시간은 데이터에 없으니 출발 전에 전화로 지금 진료가 가능한지 확인하세요.</p>
        </>
      ) : (
        <p className="mt-1 text-sm text-muted">위치를 알려 주지 않아 가까운 병원을 고를 수 없습니다. 지역 이름으로 병원을 물어보거나 가까운 동물병원에 바로 연락하세요.</p>
      )}
    </div>
  );
}

function AnswerView({ answer, question }: { answer: Answer; question?: string }) {
  return (
    <>
      {answer.urgent ? <UrgentBox {...answer.urgent} /> : null}
      {answer.safetyNotice ? <p role="note" className="mb-3 rounded-lg bg-warn/10 p-3">{answer.safetyNotice}</p> : null}
      {answer.notice ? (
        <p role={answer.notice === "error" ? "alert" : "status"} className={answer.notice === "error" ? "text-danger" : "text-warn-strong"}>
          {answer.content}
        </p>
      ) : (
        <Markdown text={answer.content} />
      )}
      {answer.abstained && answer.route === "rag" ? (
        <p className="mt-2 text-sm text-muted">증상이 걱정되면 지역 이름으로 가까운 동물병원을 물어보세요. 예: “강남구 동물병원 알려줘”</p>
      ) : null}
      {answer.notice ? null : (
        <>
          <Feedback answer={answer} question={question} />
          <Evidence route={answer.route} rows={answer.evidenceRows ?? []} />
        </>
      )}
    </>
  );
}

function PendingView({ pending }: { pending: Pending }) {
  return (
    <>
      {pending.answer.urgent ? <UrgentBox {...pending.answer.urgent} /> : null}
      {pending.places ? <Markdown text={pending.places} /> : null}
      {pending.text ? (
        <div aria-live="polite">
          <Markdown text={pending.text + " ▌"} />
        </div>
      ) : (
        <p role="status" className="text-muted">⏳ {pending.step}</p>
      )}
    </>
  );
}

function Bubble({ role, children }: { role: "user" | "assistant"; children: React.ReactNode }) {
  const mine = role === "user";
  return (
    <div className={`flex ${mine ? "justify-end" : "justify-start"}`} data-role={role}>
      <div className={`max-w-[85%] rounded-2xl px-4 py-3 ${mine ? "bg-accent text-white" : "border border-line bg-white"}`}>{children}</div>
    </div>
  );
}

/** The question an answer replied to (for the review a guardian may send). */
function askedBefore(messages: Message[], index: number): string | undefined {
  const previous = messages[index - 1];
  return previous?.role === "user" ? previous.content : undefined;
}

export default function Chat() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [pending, setPending] = useState<Pending | null>(null);
  const [draft, setDraft] = useState("");
  const memory = useRef<Memory>({ upto: 0, summary: "" });
  const controller = useRef<AbortController | null>(null);
  const bottom = useRef<HTMLDivElement>(null);

  useEffect(() => {
    warmUp();
    return () => controller.current?.abort();
  }, []);

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, pending]);

  async function send(question: string) {
    const history = historyOf(messages);
    setMessages((current) => [...current, { role: "user", content: question }]);
    let state = startPending();
    setPending(state);
    controller.current = new AbortController();
    try {
      for await (const event of askChat({ question, history, memory: memory.current }, controller.current.signal)) {
        const next = applyEvent(state, event);
        state = next.pending;
        if (next.memory) memory.current = next.memory;
        setPending(state);
      }
    } catch (error) {
      if ((error as Error).name === "AbortError") return;
    }
    setMessages((current) => [...current, finish(state, FAILED)]);
    setPending(null);
  }

  function submit(event: React.FormEvent) {
    event.preventDefault();
    const question = draft.trim();
    if (!question || pending) return;
    setDraft("");
    void send(question);
  }

  return (
    <section className="flex flex-1 flex-col">
      <div className="flex-1 space-y-4 pb-4" aria-label="대화">
        {messages.length === 0 && !pending ? (
          <p className="rounded-xl bg-accent/5 p-4 text-muted">
            반려견의 증상, 가까운 병원, 반려동물 관련 보고서 내용을 물어보세요. 응급 징후가 보이면 답보다 먼저 알려 드립니다.
          </p>
        ) : null}
        {messages.map((message, index) => (
          <Bubble key={index} role={message.role}>
            {message.role === "user" ? (
              <p className="whitespace-pre-wrap">{message.content}</p>
            ) : (
              <AnswerView answer={message} question={askedBefore(messages, index)} />
            )}
          </Bubble>
        ))}
        {pending ? (
          <Bubble role="assistant">
            <PendingView pending={pending} />
          </Bubble>
        ) : null}
        <div ref={bottom} />
      </div>
      <form onSubmit={submit} className="sticky bottom-0 flex gap-2 border-t border-line bg-page py-3">
        <label htmlFor="question" className="sr-only">질문</label>
        <textarea
          id="question"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) submit(event);
          }}
          placeholder={PLACEHOLDER}
          maxLength={1000}
          rows={1}
          disabled={pending !== null}
          className="min-h-11 flex-1 resize-none rounded-xl border border-line bg-white px-3 py-2 text-ink placeholder:text-muted focus:border-accent focus:outline-none disabled:bg-line/40"
        />
        <button type="submit" disabled={pending !== null || !draft.trim()} className="rounded-xl bg-accent px-4 font-semibold text-white disabled:opacity-40">
          보내기
        </button>
      </form>
    </section>
  );
}
