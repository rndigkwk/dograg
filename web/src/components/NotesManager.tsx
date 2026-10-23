"use client";

import { useEffect, useState } from "react";

import { listNotes, MAX_NOTES, type Note, noteDate, notesEnabled, removeAllNotes, removeNote, setNotesEnabled } from "@/lib/notes";
import { signInWithGoogle, supabase } from "@/lib/supabase";

import { useAuth } from "./AuthProvider";

/** The memory page (ADR-0009): what is remembered, with delete one / delete all and the on/off switch. */
export default function NotesManager() {
  const { session, ready } = useAuth();
  const [notes, setNotes] = useState<Note[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const signedIn = Boolean(session);

  useEffect(() => {
    if (!signedIn) return;
    listNotes(supabase()).then(setNotes, () => setError("기억을 불러오지 못했습니다. 잠시 뒤 새로고침해 주세요."));
  }, [signedIn]);

  if (!ready) return null;
  if (!session) {
    return (
      <div className="rounded-xl border border-line bg-white p-4">
        <p>지난 상담 기억은 로그인한 경우에만 쓸 수 있습니다. 기록은 계정에만 저장되고 나만 볼 수 있습니다.</p>
        <button type="button" onClick={() => void signInWithGoogle()} className="mt-3 rounded-lg bg-accent px-4 py-2 font-semibold text-white">
          Google로 로그인
        </button>
      </div>
    );
  }

  async function run(action: () => Promise<void>, failed: string) {
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch {
      setError(failed);
    } finally {
      setBusy(false);
    }
  }

  const enabled = notesEnabled(session);
  const toggle = () => run(() => setNotesEnabled(supabase(), !enabled), "설정을 바꾸지 못했습니다. 잠시 뒤 다시 시도해 주세요.");
  const remove = (id: string) =>
    run(async () => {
      await removeNote(supabase(), id);
      setNotes((shown) => shown?.filter((note) => note.id !== id) ?? null);
    }, "지우지 못했습니다. 잠시 뒤 다시 시도해 주세요.");
  const removeAll = () => {
    if (!window.confirm("저장한 상담 기록을 모두 지웁니다. 되돌릴 수 없습니다.")) return;
    void run(async () => {
      await removeAllNotes(supabase());
      setNotes([]);
    }, "지우지 못했습니다. 잠시 뒤 다시 시도해 주세요.");
  };

  return (
    <div className="space-y-4">
      <section aria-label="기억 사용 설정" className="rounded-xl border border-line bg-white p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="font-semibold">새 질문에 지난 상담 기억 사용: {enabled ? "켜짐" : "꺼짐"}</p>
            <p className="text-sm text-muted">켜면 최근 기록 5개를 질문과 함께 보내, 답변이 이어지는 상황을 알고 답합니다. 기록은 근거가 아니라 참고로만 씁니다.</p>
          </div>
          <button type="button" role="switch" aria-checked={enabled} disabled={busy} onClick={() => void toggle()} className={`rounded-lg px-4 py-2 font-semibold disabled:opacity-50 ${enabled ? "border border-line" : "bg-accent text-white"}`}>
            {enabled ? "끄기" : "켜기"}
          </button>
        </div>
      </section>

      {error ? <p role="alert" className="text-sm text-danger">{error}</p> : null}

      <section aria-label="저장한 상담 기록" className="rounded-xl border border-line bg-white p-4">
        <div className="mb-2 flex items-center justify-between">
          <h2 className="font-bold">
            저장한 상담 기록 {notes ? `(${notes.length}/${MAX_NOTES})` : ""}
          </h2>
          {notes?.length ? (
            <button type="button" disabled={busy} onClick={removeAll} className="rounded-lg border border-danger/40 px-3 py-1 text-sm text-danger disabled:opacity-50">
              모두 지우기
            </button>
          ) : null}
        </div>
        {notes === null ? (
          <p className="text-muted">불러오는 중입니다…</p>
        ) : notes.length === 0 ? (
          <p className="text-muted">아직 저장한 기록이 없습니다. 질병 문의 답변 아래의 “이 상담 기억하기”로 저장할 수 있습니다.</p>
        ) : (
          <ul className="space-y-2">
            {notes.map((note) => (
              <li key={note.id} className="flex items-start justify-between gap-3 rounded-lg border border-line p-3">
                <div>
                  <p className="text-xs text-muted">{noteDate(note.created_at)}</p>
                  <p className="mt-0.5 whitespace-pre-wrap">{note.note}</p>
                </div>
                <button type="button" disabled={busy} onClick={() => void remove(note.id)} aria-label={`${noteDate(note.created_at)} 기록 지우기`} className="shrink-0 rounded-lg border border-line px-2 py-1 text-sm disabled:opacity-50">
                  지우기
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
