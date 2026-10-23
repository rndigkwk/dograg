"use client";

import { useState } from "react";

import { FEEDBACK_REASONS, sendReason, sendReview, sendVote } from "@/lib/api";
import type { Answer } from "@/lib/chat";
import Icon from "./Icon";

const THANKS = "보내 주셔서 고맙습니다. 답변을 고치는 데 쓰겠습니다.";

/** 👍/👎 under an answer with a trace; after 👎, why, and (with consent) the turn for review
 * (app_pages/rag.py render_feedback). */
export default function Feedback({ answer, question }: { answer: Answer; question?: string }) {
  const [vote, setVote] = useState<boolean | null>(null);
  const [reason, setReason] = useState<string | null>(null);
  const [consent, setConsent] = useState(false);
  const [review, setReview] = useState<"idle" | "sending" | "sent" | "failed">("idle");
  const traceId = answer.traceId;
  if (!traceId) return null;

  function choose(helpful: boolean) {
    if (vote === helpful) {
      setVote(null); // cleared on screen; the score already sent stays, as on the Streamlit page
      return;
    }
    setVote(helpful);
    void sendVote(traceId!, helpful);
  }

  async function submit() {
    setReview("sending");
    const saved = await sendReview({ traceId: traceId!, question: question!, answer: answer.content, route: answer.route, reason, evidenceRows: answer.evidenceRows });
    setReview(saved ? "sent" : "failed");
  }

  const button = (helpful: boolean, label: string, icon: React.ReactNode) => (
    <button
      type="button"
      aria-label={label}
      aria-pressed={vote === helpful}
      onClick={() => choose(helpful)}
      className={`rounded-full border px-3 py-1 ${vote === helpful ? "border-accent bg-accent/10" : "border-line"}`}
    >
      {icon}
    </button>
  );

  return (
    <div className="mt-4 text-sm">
      <div className="flex gap-2">
        {button(true, "도움이 됐어요", <Icon name="thumbUp" size={18} />)}
        {button(false, "아쉬워요", <Icon name="thumbDown" size={18} />)}
      </div>
      {vote === false ? (
        <fieldset className="mt-3">
          <legend className="mb-1">어떤 점이 아쉬웠나요?</legend>
          <div className="flex flex-wrap gap-x-4 gap-y-1">
            {FEEDBACK_REASONS.map((item) => (
              <label key={item} className="flex items-center gap-1">
                <input
                  type="radio"
                  name={`reason-${traceId}`}
                  checked={reason === item}
                  onChange={() => {
                    setReason(item);
                    void sendReason(traceId, item);
                  }}
                />
                {item}
              </label>
            ))}
          </div>
          {question ? (
            review === "sent" ? (
              <p className="mt-3 text-muted">{THANKS}</p>
            ) : (
              <div className="mt-3 space-y-2">
                <label className="flex items-start gap-2">
                  <input type="checkbox" checked={consent} onChange={(event) => setConsent(event.target.checked)} className="mt-1" />
                  <span>이 질문과 답변을 개선에 쓰도록 보내기 (전화번호·주소 같은 개인정보는 가린 뒤 저장합니다)</span>
                </label>
                {consent ? (
                  <button type="button" disabled={review === "sending"} onClick={submit} className="rounded-lg bg-accent px-3 py-1 text-white disabled:opacity-40">
                    보내기
                  </button>
                ) : null}
                {review === "failed" ? <p className="text-danger">지금은 보내지 못했습니다. 잠시 뒤 다시 시도해 주세요.</p> : null}
              </div>
            )
          ) : null}
        </fieldset>
      ) : null}
    </div>
  );
}
