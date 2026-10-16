"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { HttpError, postStream, warmUp } from "@/lib/api";
import { profileSummary } from "@/lib/profile";
import {
  applyVisitEvent,
  emptyRun,
  EXPIRED,
  HANDOFF_KEY,
  MAX_ANSWER_CHARS,
  MAX_CONSULTATION_CHARS,
  outcomeLine,
  type Run,
  URGENT,
} from "@/lib/visitPrep";

import Markdown from "./Markdown";
import { useRecords } from "./useRecords";

const FAILED = "보고서를 만들지 못했습니다. 잠시 뒤 다시 시도해 주세요.";

function UrgentNotice() {
  return (
    <div role="alert" className="rounded-lg border border-danger/40 bg-danger/5 p-3">
      <p className="font-semibold text-danger">{URGENT}</p>
      <Link href="/places" className="mt-1 inline-block text-sm text-accent underline">
        🏥 시설 찾기에서 가까운 동물병원 찾기
      </Link>
    </div>
  );
}

function download(report: string) {
  const url = URL.createObjectURL(new Blob([report], { type: "text/markdown;charset=utf-8" }));
  const link = Object.assign(document.createElement("a"), { href: url, download: "visit_report.md" });
  link.click();
  URL.revokeObjectURL(url);
}

/** The visit-prep report page (app_pages/visit_prep.py): consultation in, a reviewed report out. */
export default function VisitPrep() {
  const [consultation, setConsultation] = useState("");
  const [region, setRegion] = useState("");
  const [profile, setProfile] = useState("");
  const [answer, setAnswer] = useState("");
  const [run, setRun] = useState<Run | null>(null);
  const [working, setWorking] = useState(false);
  const controller = useRef<AbortController | null>(null);
  const { records } = useRecords();

  // The dog's saved profile (the account's when signed in) fills an empty box once it is known.
  useEffect(() => {
    if (!records) return;
    records
      .profile()
      .then((saved) => {
        if (saved) setProfile((typed) => typed || profileSummary(saved).slice(0, 300));
      })
      .catch(() => {});
  }, [records]);

  useEffect(() => {
    warmUp();
    try {
      const carried = sessionStorage.getItem(HANDOFF_KEY);
      if (carried) {
        setConsultation(carried.slice(0, MAX_CONSULTATION_CHARS));
        sessionStorage.removeItem(HANDOFF_KEY);
      }
    } catch {
      // storage blocked: the box starts empty
    }
    return () => controller.current?.abort();
  }, []);

  async function stream(path: string, body: unknown, start: Run) {
    setWorking(true);
    let state = start;
    setRun(state);
    controller.current = new AbortController();
    try {
      for await (const event of postStream(path, body, controller.current.signal)) {
        state = applyVisitEvent(state, event);
        setRun(state);
      }
      if (!state.paused && !state.result && !state.notice) state = { ...state, notice: { kind: "error", message: FAILED } };
    } catch (error) {
      if ((error as Error).name === "AbortError") return;
      const message = error instanceof HttpError && error.status === 404 ? EXPIRED : FAILED;
      state = { ...state, paused: null, notice: { kind: "error", message } };
    }
    setRun(state);
    setWorking(false);
  }

  function start(event: React.FormEvent) {
    event.preventDefault();
    const text = consultation.trim();
    if (!text || working) return;
    setAnswer("");
    void stream("/visit-prep", { consultation: text, region: region.trim(), profile: profile.trim() }, emptyRun());
  }

  function resume(skip: boolean) {
    if (!run?.paused || working) return;
    const { threadId } = run.paused;
    // The same run goes on: its steps so far stay, the questions go.
    void stream(`/visit-prep/${encodeURIComponent(threadId)}/answer`, { answer: skip ? "" : answer.trim() }, { ...run, paused: null, notice: null });
  }

  const field = "w-full rounded-lg border border-line bg-white px-3 py-2";
  return (
    <div className="space-y-5">
      <form onSubmit={start} className="space-y-3 rounded-xl border border-line bg-white p-4">
        <label className="block">
          <span className="text-sm font-semibold">상담 내용</span>
          <textarea
            value={consultation}
            onChange={(event) => setConsultation(event.target.value)}
            maxLength={MAX_CONSULTATION_CHARS}
            rows={4}
            disabled={working}
            placeholder="예: 4살 말티즈가 어제부터 설사를 하고 오늘 아침에 두 번 토했어요. 병원비도 걱정돼요."
            className={field}
          />
        </label>
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="block">
            <span className="text-sm">근처 동물병원을 찾을 지역 (선택)</span>
            <input value={region} onChange={(event) => setRegion(event.target.value)} maxLength={30} disabled={working} placeholder="예: 강남구" className={field} />
          </label>
          <label className="block">
            <span className="text-sm">반려견 정보 (선택)</span>
            <input value={profile} onChange={(event) => setProfile(event.target.value)} maxLength={300} disabled={working} placeholder="예: 말티즈, 4살, 3.2kg" className={field} />
          </label>
        </div>
        <button type="submit" disabled={working || !consultation.trim()} className="rounded-lg bg-accent px-4 py-2 font-semibold text-white disabled:opacity-40">
          📝 방문 준비 보고서 만들기
        </button>
        <p className="text-xs text-muted">한 번에 1~2분, 모델 호출 10~20회가 들어 하루 2번까지 만들 수 있습니다. 질문 한도에도 한 번으로 셉니다.</p>
      </form>

      {run?.urgent ? <UrgentNotice /> : null}

      {run && (working || run.steps.length) ? (
        <section aria-label="진행 과정" className="rounded-xl border border-line bg-white p-4 text-sm">
          <p className="font-semibold">{working ? "⏳ 보고서를 만드는 중입니다. 1~2분 걸립니다." : "진행 과정"}</p>
          <ul className="mt-2 space-y-1">
            {run.steps.map((line, index) => (
              <li key={index}>✓ {line}</li>
            ))}
          </ul>
        </section>
      ) : null}

      {run?.notice ? (
        <p role={run.notice.kind === "error" ? "alert" : "status"} className={run.notice.kind === "error" ? "text-danger" : "text-warn-strong"}>
          {run.notice.message}
        </p>
      ) : null}

      {run?.paused ? (
        <section aria-label="보호자 질문" className="space-y-3 rounded-xl border border-accent/40 bg-white p-4">
          <p className="font-semibold">보고서를 더 정확하게 만들기 위해 몇 가지 여쭤볼게요</p>
          <ol className="list-decimal space-y-1 pl-5">
            {run.paused.questions.map((question) => (
              <li key={question}>{question}</li>
            ))}
          </ol>
          <label className="block">
            <span className="text-sm">답변 (아는 것만 적어도 됩니다)</span>
            <textarea
              value={answer}
              onChange={(event) => setAnswer(event.target.value)}
              maxLength={MAX_ANSWER_CHARS}
              rows={3}
              disabled={working}
              placeholder="예: 어제 저녁부터요. 하루에 세 번 정도 했고 밥은 반만 먹었어요."
              className={field}
            />
          </label>
          <div className="flex flex-wrap gap-2">
            <button type="button" disabled={working} onClick={() => resume(false)} className="rounded-lg bg-accent px-4 py-2 font-semibold text-white disabled:opacity-40">
              답하고 보고서 만들기
            </button>
            <button type="button" disabled={working} onClick={() => resume(true)} className="rounded-lg border border-line px-4 py-2 disabled:opacity-40">
              건너뛰고 바로 만들기
            </button>
          </div>
          <p className="text-xs text-muted">30분 안에 답해 주세요. 답하거나 건너뛰어도 새 보고서로 세지 않습니다.</p>
        </section>
      ) : null}

      {run?.result ? (
        <section aria-label="방문 준비 보고서" className="space-y-3">
          {run.result.urgent && !run.urgent ? <UrgentNotice /> : null}
          <p role="status" className={run.result.passed ? "rounded-lg bg-accent/10 p-3" : "rounded-lg bg-warn/10 p-3"}>
            {outcomeLine(run.result)}
          </p>
          <article className="rounded-xl border border-line bg-white p-4">
            <Markdown text={run.result.report} />
          </article>
          <button type="button" onClick={() => download(run.result!.report)} className="rounded-lg border border-line bg-white px-4 py-2">
            ⬇ 보고서 내려받기 (.md)
          </button>
        </section>
      ) : null}
    </div>
  );
}
