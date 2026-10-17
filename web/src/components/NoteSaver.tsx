"use client";

import Link from "next/link";
import { useState } from "react";

import { askNote } from "@/lib/api";
import { addNote, cleanNote, NOTE_MAX_CHARS, notesEnabled, setNotesEnabled } from "@/lib/notes";
import { supabase } from "@/lib/supabase";

import { useAuth } from "./AuthProvider";

type Step = { kind: "idle" } | { kind: "writing" } | { kind: "edit"; text: string } | { kind: "saving"; text: string } | { kind: "saved" } | { kind: "error"; message: string; text?: string };

/** Under a health answer, for a signed-in guardian: "이 상담 기억하기" (ADR-0009). The API writes a short
 * note (one model call); the guardian edits or cancels it before it is saved to their account. The
 * first save also offers to turn the memory on; nothing is used until it is on. */
export default function NoteSaver({ question, answer, threadId, onSaved }: { question: string; answer: string; threadId: string | null; onSaved?: () => void }) {
  const { session } = useAuth();
  const [step, setStep] = useState<Step>({ kind: "idle" });
  const [useIt, setUseIt] = useState(true);
  if (!session) return null;
  const enabled = notesEnabled(session);

  async function write() {
    setStep({ kind: "writing" });
    try {
      const { note } = await askNote(question, answer);
      setStep({ kind: "edit", text: note });
    } catch (error) {
      setStep({ kind: "error", message: (error as Error).message });
    }
  }

  async function save(text: string) {
    const note = cleanNote(text);
    if (!note) return;
    setStep({ kind: "saving", text: note });
    try {
      await addNote(supabase(), note, threadId);
      if (!enabled && useIt) await setNotesEnabled(supabase(), true);
      setStep({ kind: "saved" });
      onSaved?.();
    } catch {
      setStep({ kind: "error", message: "저장하지 못했습니다. 기록은 30개까지라, 많다면 기억 화면에서 지운 뒤 다시 시도해 주세요.", text: note });
    }
  }

  if (step.kind === "idle") {
    return (
      <button type="button" onClick={() => void write()} className="mt-3 ml-2 rounded-lg border border-line px-3 py-1 text-sm">
        🗂 이 상담 기억하기
      </button>
    );
  }
  if (step.kind === "writing") return <p role="status" className="mt-3 text-sm text-muted">기록을 정리하는 중입니다…</p>;
  if (step.kind === "saved") {
    return (
      <p role="status" className="mt-3 text-sm">
        기억했습니다.{" "}
        <Link href="/memory" className="text-accent underline">
          기억 보기·지우기
        </Link>
      </p>
    );
  }
  const text = step.kind === "edit" || step.kind === "saving" ? step.text : (step.text ?? "");
  return (
    <div role="region" aria-label="상담 기록 저장" className="mt-3 rounded-xl border border-accent/40 bg-white p-3 text-sm">
      {step.kind === "error" ? <p role="alert" className="mb-2 text-danger">{step.message}</p> : null}
      {step.kind === "error" && !step.text ? (
        <button type="button" onClick={() => setStep({ kind: "idle" })} className="rounded-lg border border-line px-3 py-1">
          닫기
        </button>
      ) : (
        <>
          <label htmlFor="note-text" className="font-semibold">
            기억할 내용 (고쳐 쓸 수 있어요)
          </label>
          <textarea
            id="note-text"
            value={text}
            maxLength={NOTE_MAX_CHARS}
            rows={3}
            disabled={step.kind === "saving"}
            onChange={(e) => setStep({ kind: "edit", text: e.target.value })}
            className="mt-1 w-full rounded-lg border border-line p-2"
          />
          <p className="mt-1 text-xs text-muted">
            계정에만 저장되고(나만 볼 수 있음), 날짜와 함께 남습니다. 기억 화면에서 언제든 지울 수 있습니다.
          </p>
          {!enabled ? (
            <label className="mt-2 flex items-start gap-2">
              <input type="checkbox" checked={useIt} onChange={(e) => setUseIt(e.target.checked)} className="mt-1" />
              <span>새 질문에 지난 상담 기억 사용 (최근 기록 5개를 답변에 참고합니다. 지금은 꺼져 있어요)</span>
            </label>
          ) : null}
          <div className="mt-2 flex gap-2">
            <button type="button" disabled={step.kind === "saving" || !cleanNote(text)} onClick={() => void save(text)} className="rounded-lg bg-accent px-3 py-1.5 font-semibold text-white disabled:opacity-50">
              저장
            </button>
            <button type="button" disabled={step.kind === "saving"} onClick={() => setStep({ kind: "idle" })} className="rounded-lg border border-line px-3 py-1.5">
              취소
            </button>
          </div>
        </>
      )}
    </div>
  );
}
