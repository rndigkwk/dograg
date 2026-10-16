"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { askChat, type Memory, warmUp } from "@/lib/api";
import { type Answer, applyEvent, type Emergency, finish, type Hospital, historyOf, type Message, type Pending, startPending } from "@/lib/chat";

import { HANDOFF_KEY, MAX_CONSULTATION_CHARS } from "@/lib/visitPrep";
import { type AccountRecords, DeviceRecords, moveDeviceToAccount } from "@/lib/records";
import { messagesOf, recordTurn, STORAGE_NOTICE, takeNotice, type Thread } from "@/lib/store";

import { locate, type Location } from "@/lib/location";
import { isEmpty, type MemorySuggestion, type PetProfile } from "@/lib/profile";

import Conversations from "./Conversations";
import MemoryCard from "./MemoryCard";
import ProfileForm from "./ProfileForm";
import { useRecords } from "./useRecords";
import { deleteAccount } from "@/lib/supabase";
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
        <p className="mt-1 text-sm text-muted">아래의 “현재 위치 사용”을 누르면 다음부터 가까운 병원을 여기에 바로 보여 드립니다. 지금은 지역 이름으로 병원을 물어보거나 가까운 동물병원에 바로 연락하세요.</p>
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
          <PlaceLinks rows={answer.hospitalRows ?? []} />
          {question && answer.route === "rag" && !answer.abstained ? <VisitPrepLink question={question} /> : null}
          <Feedback answer={answer} question={question} />
          <Evidence route={answer.route} rows={answer.evidenceRows ?? []} />
        </>
      )}
    </>
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

/** Under a health answer: carry the question to the visit-prep page (app_pages/rag.py render_visit_prep_button).
 * Not under an abstention: there was no evidence, and a report would spend 10-20 model calls on the same empty search. */
function VisitPrepLink({ question }: { question: string }) {
  const router = useRouter();
  return (
    <button
      type="button"
      onClick={() => {
        try {
          sessionStorage.setItem(HANDOFF_KEY, question.slice(0, MAX_CONSULTATION_CHARS));
        } catch {
          // storage blocked: the page opens with an empty box
        }
        router.push("/visit-prep");
      }}
      className="mt-3 rounded-lg border border-line px-3 py-1 text-sm"
    >
      📝 이 상담으로 방문 준비 보고서 만들기
    </button>
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
  const { records, storage } = useRecords();
  const [loaded, setLoaded] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [accountNote, setAccountNote] = useState<string | null>(null);
  // Signed in with records still on this device: how many, to offer moving them into the account.
  const [deviceLeft, setDeviceLeft] = useState(0);
  const [notice, setNotice] = useState(false);
  const [threads, setThreads] = useState<Thread[]>([]);
  const [current, setCurrent] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [pending, setPending] = useState<Pending | null>(null);
  const [draft, setDraft] = useState("");
  const [listOpen, setListOpen] = useState(false);
  const [profile, setProfile] = useState<PetProfile | null>(null);
  const [suggestion, setSuggestion] = useState<MemorySuggestion | null>(null);
  const [location, setLocation] = useState<Location | null>(null);
  const [locationNote, setLocationNote] = useState<string | null>(null);
  // This tab only, like the Streamlit session: facts declined, and "do not offer a profile" once refused.
  const declined = useRef<string[]>([]);
  const profileRefused = useRef(false);
  // {thread id: summary of its older turns, as the API last returned it}; this tab only, like the Streamlit page.
  const memories = useRef(new Map<string, Memory>());
  const controller = useRef<AbortController | null>(null);
  const bottom = useRef<HTMLDivElement>(null);

  useEffect(() => {
    warmUp();
    return () => controller.current?.abort();
  }, []);

  // Load whoever's records the page now shows: the account after sign-in, this browser after sign-out.
  // Nothing of the previous person stays on screen.
  useEffect(() => {
    if (!records) return;
    let stale = false;
    setLoaded(false);
    setCurrent(null);
    setMessages([]);
    setSuggestion(null);
    memories.current.clear();
    Promise.all([records.threads(), records.profile()])
      .then(async ([loadedThreads, loadedProfile]) => {
        if (stale) return;
        setThreads(loadedThreads);
        setProfile(loadedProfile);
        setSaveError(null);
        if (records.where === "device") {
          setNotice(takeNotice(storage));
          setDeviceLeft(0);
        } else {
          setNotice(false);
          const device = new DeviceRecords(storage);
          const [left, leftProfile] = await Promise.all([device.threads(), device.profile()]);
          if (!stale) setDeviceLeft(left.length + (leftProfile ? 1 : 0));
        }
        setLoaded(true);
      })
      .catch(() => {
        if (stale) return;
        setThreads([]);
        setProfile(null);
        setSaveError("계정의 기록을 불러오지 못했습니다. 잠시 뒤 새로고침해 주세요.");
        setLoaded(true);
      });
    return () => {
      stale = true;
    };
  }, [records, storage]);

  /** Runs a write to the records; a failure is shown, not thrown (the answer is already on screen). */
  async function write(action: () => Promise<void>) {
    try {
      await action();
      setSaveError(null);
    } catch {
      setSaveError(records?.where === "account" ? "계정에 저장하지 못했습니다. 잠시 뒤 다시 시도해 주세요." : "이 브라우저에 저장하지 못했습니다.");
    }
  }

  async function moveToAccount() {
    if (!records || records.where !== "account") return;
    await write(async () => {
      const kept = await moveDeviceToAccount(new DeviceRecords(storage), records as AccountRecords);
      setThreads(kept);
      setProfile(await records.profile());
      setDeviceLeft(0);
    });
  }

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, pending]);

  function open(id: string | null) {
    setCurrent(id);
    setMessages(messagesOf(threads.find((thread) => thread.id === id)));
    setListOpen(false);
  }

  function remove() {
    const rest = threads.filter((thread) => thread.id !== current);
    const gone = current;
    if (records && gone) void write(() => records.save(rest, null, [gone]));
    setThreads(rest);
    setCurrent(null);
    setMessages([]);
  }

  function clearAll() {
    const account = records?.where === "account";
    const message = account
      ? "계정에 저장된 대화와 반려견 정보를 서버에서 모두 지웁니다. 되돌릴 수 없습니다."
      : "이 브라우저에 저장된 대화와 반려견 정보를 모두 지웁니다. 되돌릴 수 없습니다.";
    if (!records || !window.confirm(message)) return;
    void write(() => records.clear());
    memories.current.clear();
    setThreads([]);
    setCurrent(null);
    setMessages([]);
    setNotice(false);
    setProfile(null);
    setSuggestion(null);
  }

  async function removeAccount() {
    const sure = window.confirm(
      "라그도그 계정을 삭제합니다. 계정에 저장된 대화와 반려견 정보도 서버에서 함께 지워지고, 되돌릴 수 없습니다.\n\n" +
        "Google의 '라그도그 로그인 허용'은 Google 계정 → 보안 → 타사 연결에서 직접 끊을 수 있습니다.",
    );
    if (!sure) return;
    try {
      await deleteAccount(); // signs out: the records switch to this browser's
      setAccountNote("계정을 삭제했습니다. 이 브라우저에 남은 로그인 전 기록은 그대로입니다.");
    } catch {
      setSaveError("계정을 삭제하지 못했습니다. 잠시 뒤 다시 시도해 주세요.");
    }
  }

  function keepProfile(next: PetProfile | null) {
    if (records) void write(() => records.saveProfile(next));
    setProfile(isEmpty(next) ? null : next);
  }

  function answerSuggestion(save: boolean) {
    if (!suggestion) return;
    if (save) keepProfile(suggestion.profile);
    else if (suggestion.update) declined.current.push(suggestion.summary);
    else profileRefused.current = true;
    setSuggestion(null);
  }

  async function useLocation() {
    setLocationNote("위치를 확인하는 중입니다…");
    const found = await locate();
    if ("location" in found) {
      setLocation(found.location);
      setLocationNote("현재 위치를 사용합니다. 응급 안내와 가까운 병원 찾기에 씁니다(저장하지 않음).");
    } else {
      setLocationNote(`${found.error} 지역명으로 병원을 검색할 수 있습니다.`);
    }
  }

  async function send(question: string) {
    const thread = current;
    const history = historyOf(messages);
    setMessages((shown) => [...shown, { role: "user", content: question }]);
    let state = startPending();
    setPending(state);
    setSuggestion(null);
    const request = {
      question,
      history,
      memory: { upto: 0, summary: "" },
      profile: isEmpty(profile) ? null : profile,
      location,
      // Until storage is read the profile is a stand-in; a suggestion against it would replace the stored one.
      suggest_memory: loaded && records !== null && (records.where === "account" || Boolean(storage)) && !(isEmpty(profile) && profileRefused.current),
      declined_memory: declined.current.slice(-20),
    };
    let memory = (thread && memories.current.get(thread)) || { upto: 0, summary: "" };
    controller.current = new AbortController();
    try {
      for await (const event of askChat({ ...request, memory }, controller.current.signal)) {
        const next = applyEvent(state, event);
        state = next.pending;
        if (next.memory) memory = next.memory;
        if (next.suggestion) setSuggestion(next.suggestion);
        setPending(state);
      }
    } catch (error) {
      if ((error as Error).name === "AbortError") return;
    }
    const answer = finish(state, FAILED);
    if (!answer.notice) {
      // Only answers are kept; a refused or failed question is shown but not stored.
      const recorded = recordTurn(threads, thread, question, answer);
      const kept = new Set(recorded.threads.map((t) => t.id));
      const dropped = threads.filter((t) => !kept.has(t.id)).map((t) => t.id); // past the 20 kept
      const changed = recorded.threads.find((t) => t.id === recorded.id) ?? null;
      if (records) void write(() => records.save(recorded.threads, changed, dropped));
      setThreads(recorded.threads);
      setCurrent(recorded.id);
      memories.current.set(recorded.id, memory);
    }
    setMessages((shown) => [...shown, answer]);
    setPending(null);
  }

  function submit(event: React.FormEvent) {
    event.preventDefault();
    const question = draft.trim();
    if (!question || pending) return;
    setDraft("");
    void send(question);
  }

  const profileForm = <ProfileForm profile={profile} onSave={keepProfile} />;
  const list = (
    <Conversations
      threads={threads}
      current={current}
      busy={pending !== null}
      status={!loaded ? "loading" : records?.where === "account" || storage ? "ready" : "unavailable"}
      where={records?.where ?? "device"}
      onDeleteAccount={() => void removeAccount()}
      onOpen={open}
      onDelete={remove}
      onClear={clearAll}
    />
  );

  return (
    <div className="flex flex-1 gap-6">
      <aside className="hidden w-64 shrink-0 md:block" aria-label="대화 기록">
        <div className="sticky top-4 space-y-4">
          {list}
          {profileForm}
        </div>
      </aside>
      <section className="flex min-w-0 flex-1 flex-col">
        <button
          type="button"
          onClick={() => setListOpen(!listOpen)}
          aria-expanded={listOpen}
          className="mb-3 self-start rounded-lg border border-line bg-white px-3 py-1 text-sm md:hidden"
        >
          대화 기록 {threads.length ? `(${threads.length})` : ""}
        </button>
        {listOpen ? (
          <div className="mb-4 space-y-4 rounded-xl border border-line bg-white p-3 md:hidden">
            {list}
            {profileForm}
          </div>
        ) : null}
        {deviceLeft > 0 ? (
          <div role="region" aria-label="기기 기록 옮기기" className="mb-4 rounded-xl border border-accent/40 bg-white p-3 text-sm">
            <p>
              이 브라우저에 로그인 전 기록이 {deviceLeft}개 있습니다. 계정으로 옮길까요? 옮기면 다른 기기에서도 보이고, 이 브라우저의 사본은 지웁니다. 대화는 최근
              20개까지 남습니다.
            </p>
            <div className="mt-2 flex gap-2">
              <button type="button" onClick={() => void moveToAccount()} className="rounded-lg bg-accent px-3 py-1 font-semibold text-white">
                계정으로 옮기기
              </button>
              <button type="button" onClick={() => setDeviceLeft(0)} className="rounded-lg border border-line px-3 py-1">
                그대로 두기
              </button>
            </div>
          </div>
        ) : null}
        {accountNote ? (
          <p role="status" className="mb-4 rounded-xl bg-accent/5 p-3 text-sm">
            {accountNote}
          </p>
        ) : null}
        {saveError ? (
          <p role="alert" className="mb-4 text-sm text-danger">
            {saveError}
          </p>
        ) : null}
        {notice ? (
          <p role="note" className="mb-4 rounded-xl border border-accent/30 bg-accent/5 p-3 text-sm">
            {STORAGE_NOTICE}
          </p>
        ) : null}
        <div className="flex-1 space-y-4 pb-4" aria-label="대화">
          {messages.length === 0 && !pending ? (
            <p className="rounded-xl bg-accent/5 p-4 text-muted">
              반려견의 증상, 가까운 병원, 반려동물 관련 보고서 내용을 물어보세요. 응급 징후가 보이면 답보다 먼저 알려 드립니다.
            </p>
          ) : null}
          {messages.map((message, index) => (
            // Keyed by thread too: a 👍 chosen in one conversation must not show in another.
            <Bubble key={`${current ?? "new"}-${index}`} role={message.role}>
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
          {suggestion && !pending ? <MemoryCard suggestion={suggestion} onSave={() => answerSuggestion(true)} onDismiss={() => answerSuggestion(false)} /> : null}
          <div ref={bottom} />
        </div>
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <button type="button" onClick={useLocation} className="rounded-lg border border-line bg-white px-3 py-1">
            📍 {location ? "위치 다시 가져오기" : "현재 위치 사용"}
          </button>
          <span className="text-muted">{locationNote ?? "가까운 병원 검색은 위치 사용을 선택한 경우에만 직선거리로 계산합니다."}</span>
        </div>
        <form onSubmit={submit} className="sticky bottom-0 flex gap-2 border-t border-line bg-page py-3">
          <label htmlFor="question" className="sr-only">
            질문
          </label>
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
    </div>
  );
}
