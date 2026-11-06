"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useId, useState } from "react";

import { type Answer, FIRST_STEP, type Pending } from "@/lib/chat";
import type { Location } from "@/lib/location";
import { linkCitations } from "@/lib/evidence";
import { splitTodo } from "@/lib/todo";
import { HANDOFF_CUT_KEY, HANDOFF_KEY } from "@/lib/visitPrep";

import Evidence from "./Evidence";
import Feedback from "./Feedback";
import Icon from "./Icon";
import Markdown from "./Markdown";
import NoteSaver from "./NoteSaver";
import UrgentBox from "./UrgentBox";
import Waiting from "./Waiting";

// One turn of the chat: a finished answer with what goes under it, the answer being written, a bubble.

export function AnswerView({ answer, question, consultation, threadId, onNoteSaved, onRetry, onLocated }: { answer: Answer; question?: string; consultation?: { text: string; cut: boolean }; threadId?: string | null; onNoteSaved?: () => void; onRetry?: () => void; onLocated?: (location: Location) => void }) {
  return (
    <div data-answer>
      {answer.urgent ? <UrgentBox {...answer.urgent} onLocated={onLocated} /> : null}
      {answer.careLevel && !answer.urgent && !answer.notice ? <CareBadge /> : null}
      {answer.safetyNotice ? <p role="note" className="mb-3 rounded-lg bg-warn/10 p-3">{answer.safetyNotice}</p> : null}
      {answer.notice ? (
        <>
          <p role={answer.notice === "error" ? "alert" : "status"} className={answer.notice === "error" ? "text-danger" : "text-warn-strong"}>
            {answer.content}
          </p>
          {onRetry ? (
            <button type="button" onClick={onRetry} className="mt-2 rounded-lg border border-line bg-white px-3 py-1 text-sm">
              같은 질문 다시 보내기
            </button>
          ) : null}
        </>
      ) : (
        // Its [사례 n] open the card below (Evidence), on a health answer that has cards.
        <AnswerText text={answer.route === "rag" && answer.evidenceRows?.length ? linkCitations(answer.content) : answer.content} todo={answer.route === "rag"} />
      )}
      {answer.abstained && answer.route === "rag" ? (
        <p className="mt-2 text-sm text-muted">증상이 걱정되면 지역 이름으로 가까운 동물병원을 물어보세요. 예: “강남구 동물병원 알려줘”</p>
      ) : null}
      {answer.notice ? null : (
        <>
          <PlaceLinks rows={answer.hospitalRows ?? []} />
          {/* The answer first, its sources folded (2026-11-06 guardian-view mockup), then where to go next. */}
          <Evidence route={answer.route} rows={answer.evidenceRows ?? []} folded={answer.route === "rag"} />
          <Feedback answer={answer} question={question} />
          {question && answer.route === "rag" && !answer.abstained ? (
            <section aria-label="이어서 하기" className="mt-3 border-t border-line pt-3">
              <p className="mb-2 text-sm text-muted">이어서 하기</p>
              <div className="flex flex-wrap gap-2">
                <Link href="/places" className="inline-flex min-h-10 items-center rounded-full border border-accent px-3 text-sm text-accent hover:bg-accent/5">
                  <Icon name="pin" size={16} className="mr-1" />근처 동물병원 보기
                </Link>
                <Link href="/fees" className="inline-flex min-h-10 items-center rounded-full border border-accent px-3 text-sm text-accent hover:bg-accent/5">
                  <Icon name="receipt" size={16} className="mr-1" />진료비는 얼마쯤?
                </Link>
                <VisitPrepLink consultation={consultation ?? { text: question, cut: false }} />
              </div>
              <NoteSaver question={question} answer={answer.content} threadId={threadId ?? null} onSaved={onNoteSaved} />
            </section>
          ) : null}
        </>
      )}
    </div>
  );
}

/** "진료 권장": the urgency check's middle answer (src/tools/urgency.py urgency_level). Not the red
 * warning (UrgentBox): a visit soon, not now. The check does not say how soon, so no day count. */
function CareBadge() {
  return (
    <p role="note" data-care-level className="mb-3 flex items-start gap-2 rounded-lg border border-warn/40 bg-warn/10 p-3 text-sm">
      <span className="shrink-0 rounded-full bg-warn-strong px-2 py-0.5 text-xs font-bold text-white">진료 권장</span>
      <span>지금 위급해 보이지는 않지만, 며칠 안에 동물병원에서 확인해 보세요.</span>
    </p>
  );
}

/** A health answer with its "지금 할 일" list as a checklist (lib/todo.ts); other answers as written. */
function AnswerText({ text, todo }: { text: string; todo: boolean }) {
  const parts = todo ? splitTodo(text) : null;
  if (!parts) return <Markdown text={text} />;
  return (
    <>
      {parts.before ? <Markdown text={parts.before} /> : null}
      <Checklist items={parts.items} />
      {parts.after ? <Markdown text={parts.after} /> : null}
    </>
  );
}

/** Ticks stay on this screen only: nothing is saved. */
function Checklist({ items }: { items: string[] }) {
  const id = useId();
  const [done, setDone] = useState<boolean[]>(() => items.map(() => false));
  const toggle = (index: number) => setDone((was) => was.map((on, at) => (at === index ? !on : on)));
  return (
    <section aria-label="지금 할 일" data-todo className="my-3 rounded-lg border border-line bg-white p-3">
      <h3 className="mb-2 font-bold">지금 할 일</h3>
      <ul className="space-y-1">
        {items.map((item, index) => (
          <li key={index}>
            {/* Not a <label>: the item is Markdown (a block, with [사례 n] links), so it names the box instead. */}
            <div className="flex items-start gap-2">
              <input
                type="checkbox"
                aria-labelledby={`${id}-${index}`}
                checked={done[index] ?? false}
                onChange={() => toggle(index)}
                className="mt-1.5 size-4 shrink-0 cursor-pointer accent-accent"
              />
              <div id={`${id}-${index}`} onClick={(event) => {
                if (!(event.target as HTMLElement).closest("a")) toggle(index);
              }} className={`min-w-0 cursor-pointer [&_p]:m-0 ${done[index] ? "text-muted line-through" : ""}`}>
                <Markdown text={item} />
              </div>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}

/** Under a place answer: each place found, opened on the place page's map (app_pages/rag.py render_hospital_links). */
function PlaceLinks({ rows }: { rows: Record<string, unknown>[] }) {
  const places = rows.filter((row) => row.id && row.latitude !== null && row.latitude !== undefined);
  if (!places.length) return null;
  return (
    <section className="mt-3" aria-label="지도에서 위치 보기">
      <h3 className="mb-1 text-sm font-bold">지도에서 위치 보기</h3>
      <ul className="space-y-1 text-sm">
        {places.map((row) => (
          <li key={String(row.id)}>
            <Link href={`/places?id=${encodeURIComponent(String(row.id))}`} className="text-accent underline">
              {String(row.name ?? "장소")}
            </Link>{" "}
            <span className="text-muted">{String(row.road_address || row.lot_address || "")}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

/** Under a health answer: carry the conversation's questions to the visit-prep page (consultationFrom).
 * Not under an abstention: there was no evidence, and a report would spend 10-20 model calls on the same empty search. */
function VisitPrepLink({ consultation }: { consultation: { text: string; cut: boolean } }) {
  const router = useRouter();
  return (
    <button
      type="button"
      onClick={() => {
        try {
          sessionStorage.setItem(HANDOFF_KEY, consultation.text);
          if (consultation.cut) sessionStorage.setItem(HANDOFF_CUT_KEY, "1");
          else sessionStorage.removeItem(HANDOFF_CUT_KEY);
        } catch {
          // storage blocked: the page opens with an empty box
        }
        router.push("/visit-prep");
      }}
      className="inline-flex min-h-10 items-center rounded-full border border-accent px-3 text-sm text-accent hover:bg-accent/5"
    >
      <Icon name="file" size={16} className="mr-1 inline-block align-[-3px]" />이 상담으로 방문 준비 보고서 만들기
    </button>
  );
}

export function PendingView({ pending, onStop, onLocated }: { pending: Pending; onStop: () => void; onLocated?: (location: Location) => void }) {
  return (
    <>
      {pending.answer.urgent ? <UrgentBox {...pending.answer.urgent} onLocated={onLocated} /> : null}
      {pending.places ? <Markdown text={pending.places} /> : null}
      {pending.text ? (
        <div aria-live="polite">
          <Markdown text={pending.text + " ▌"} />
        </div>
      ) : (
        // Anything past the first step means the API is awake and working.
        <Waiting text={pending.step} started={pending.step !== FIRST_STEP || Boolean(pending.places)} onStop={onStop} />
      )}
      {/* Readable during the ~10 s before the first word; the finished answer shows the same rows. */}
      <Evidence route="rag" rows={pending.evidence} />
    </>
  );
}

export function Bubble({ role, children }: { role: "user" | "assistant"; children: React.ReactNode }) {
  const mine = role === "user";
  return (
    <div className={`flex ${mine ? "justify-end" : "justify-start"}`} data-role={role}>
      <div className={`max-w-[85%] rounded-2xl px-4 py-3 ${mine ? "bg-accent text-white" : "border border-line bg-white"}`}>{children}</div>
    </div>
  );
}
