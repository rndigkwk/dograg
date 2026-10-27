"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";

import { type Answer, FIRST_STEP, type Pending } from "@/lib/chat";
import type { Location } from "@/lib/location";
import { linkCitations } from "@/lib/evidence";
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
        <Markdown text={answer.route === "rag" && answer.evidenceRows?.length ? linkCitations(answer.content) : answer.content} />
      )}
      {answer.abstained && answer.route === "rag" ? (
        <p className="mt-2 text-sm text-muted">증상이 걱정되면 지역 이름으로 가까운 동물병원을 물어보세요. 예: “강남구 동물병원 알려줘”</p>
      ) : null}
      {answer.notice ? null : (
        <>
          <PlaceLinks rows={answer.hospitalRows ?? []} />
          {question && answer.route === "rag" && !answer.abstained ? (
            <>
              <VisitPrepLink consultation={consultation ?? { text: question, cut: false }} />
              <NoteSaver question={question} answer={answer.content} threadId={threadId ?? null} onSaved={onNoteSaved} />
            </>
          ) : null}
          <Feedback answer={answer} question={question} />
          <Evidence route={answer.route} rows={answer.evidenceRows ?? []} />
        </>
      )}
    </div>
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
      className="mt-3 rounded-lg border border-line px-3 py-1 text-sm"
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
