import type { Thread } from "@/lib/store";

/** The stored conversations, newest first, with new / delete / clear (src/conversation_ui.py). */
export default function Conversations(props: {
  threads: Thread[];
  current: string | null;
  busy: boolean; // an answer is being written: switching now would lose it
  status: "loading" | "ready" | "unavailable";
  where: "device" | "account"; // signed in: the account's records
  onOpen: (id: string | null) => void;
  onDelete: () => void;
  onClear: () => void;
}) {
  const { threads, current, busy, status } = props;
  return (
    <nav className="space-y-2 text-sm">
      <h2 className="font-bold">대화 기록</h2>
      <p className="text-xs text-muted">{props.where === "account" ? "계정에 저장됩니다" : "이 브라우저에만 저장됩니다"}</p>
      {status === "loading" ? <p className="text-muted">저장된 대화를 불러오는 중입니다…</p> : null}
      {status === "unavailable" ? <p className="text-muted">이 브라우저에서는 대화가 저장되지 않습니다.</p> : null}
      <button type="button" disabled={busy} onClick={() => props.onOpen(null)} className="w-full rounded-lg border border-accent px-3 py-2 font-semibold text-accent disabled:opacity-40">
        + 새 대화
      </button>
      <ul className="space-y-1">
        {threads.map((thread) => (
          <li key={thread.id}>
            <button
              type="button"
              disabled={busy}
              aria-current={thread.id === current ? "true" : undefined}
              onClick={() => props.onOpen(thread.id)}
              className={`w-full truncate rounded-lg px-3 py-2 text-left disabled:opacity-40 ${thread.id === current ? "bg-accent text-white" : "hover:bg-line/50"}`}
            >
              {thread.title}
            </button>
          </li>
        ))}
      </ul>
      {current ? (
        <button type="button" disabled={busy} onClick={props.onDelete} className="w-full rounded-lg border border-line px-3 py-2 disabled:opacity-40">
          이 대화 삭제
        </button>
      ) : null}
      <button type="button" disabled={busy} onClick={props.onClear} className="w-full rounded-lg px-3 py-2 text-danger hover:bg-danger/5 disabled:opacity-40">
        {props.where === "account" ? "계정의 기록 모두 지우기" : "이 기기의 기록 모두 지우기"}
      </button>
    </nav>
  );
}
