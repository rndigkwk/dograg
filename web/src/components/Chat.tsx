"use client";

import { useEffect, useRef, useState } from "react";

import { askChat, type Memory, warmUp } from "@/lib/api";
import { applyEvent, finish, historyOf, type Message, type Pending, startPending, takeAsked } from "@/lib/chat";
import { failureMessage } from "@/lib/failure";

import { type AccountRecords, DeviceRecords, moveDeviceToAccount } from "@/lib/records";
import { messagesOf, recordTurn, STORAGE_NOTICE, takeNotice, type Thread } from "@/lib/store";

import { locate, type Location } from "@/lib/location";
import { isEmpty, type MemorySuggestion, type PetProfile } from "@/lib/profile";

import { type ChatNote, forChat, listNotes, notesEnabled } from "@/lib/notes";
import { supabase } from "@/lib/supabase";
import { consultationFrom } from "@/lib/visitPrep";

import { useAuth } from "./AuthProvider";
import { AnswerView, Bubble, PendingView } from "./ChatMessages";
import Conversations from "./Conversations";
import MemoryCard from "./MemoryCard";
import ProfileForm from "./ProfileForm";
import { useRecords } from "./useRecords";
import { deleteAccount } from "@/lib/supabase";
import Icon from "./Icon";

const FAILED = "답변을 받지 못했습니다. 잠시 뒤 다시 질문해 주세요.";
const STOPPED = "답변을 멈췄습니다.";
const PLACEHOLDER = "예: 강아지가 계속 구토해요 / 강남구 병원을 알려주세요.";

/** The question an answer replied to (for the review a guardian may send). */
function askedBefore(messages: Message[], index: number): string | undefined {
  const previous = messages[index - 1];
  return previous?.role === "user" ? previous.content : undefined;
}

export default function Chat() {
  const { records, storage } = useRecords();
  const { session } = useAuth();
  // The latest saved consultation notes, sent with each question while "지난 상담 기억" is on (ADR-0009).
  const [chatNotes, setChatNotes] = useState<ChatNote[]>([]);
  const [notesVersion, setNotesVersion] = useState(0);
  const notesOn = records?.where === "account" && notesEnabled(session);
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
  // The guardian pressed 멈추기: the abort ends the answer with a notice (leaving the page aborts quietly).
  const stopped = useRef(false);
  const bottom = useRef<HTMLDivElement>(null);
  const box = useRef<HTMLTextAreaElement>(null);
  // The question went with Enter in the box: the box is disabled while the answer streams, which drops
  // the focus to the page, so it gets the focus back after (not after a tap on 보내기: a phone keyboard would pop up).
  const typed = useRef(false);

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

  // A question typed on the home page (components/HomeAsk.tsx): asked once the records are read, so
  // it joins the right conversation and profile. Taken out first, so a reload does not ask it again.
  useEffect(() => {
    if (!loaded) return;
    const asked = takeAsked();
    if (asked) void send(asked);
    // send is this render's; the question is taken once, when the records are first loaded
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loaded]);

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
    if (!notesOn) {
      setChatNotes([]);
      return;
    }
    let stale = false;
    listNotes(supabase())
      .then((notes) => !stale && setChatNotes(forChat(notes)))
      .catch(() => !stale && setChatNotes([]));
    return () => {
      stale = true;
    };
  }, [notesOn, notesVersion]);

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

  // Shared from an urgent warning's button: later questions use it too, as with the button below.
  function located(at: Location) {
    setLocation(at);
    setLocationNote("현재 위치를 사용합니다. 응급 안내와 가까운 병원 찾기에 씁니다(저장하지 않음).");
  }

  async function useLocation() {
    setLocationNote("위치를 확인하는 중입니다…");
    const found = await locate();
    if ("location" in found) {
      located(found.location);
    } else {
      setLocationNote(`${found.error} 지역명으로 병원을 검색할 수 있습니다.`);
    }
  }

  function stop() {
    stopped.current = true;
    controller.current?.abort();
  }

  /** A failed or stopped answer is not kept; its question goes again in its place. */
  function retry(index: number) {
    const question = askedBefore(messages, index);
    if (!question || pending) return;
    setMessages((shown) => shown.slice(0, index - 1));
    void send(question);
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
      ...(notesOn && chatNotes.length ? { notes: chatNotes } : {}),
    };
    let memory = (thread && memories.current.get(thread)) || { upto: 0, summary: "" };
    controller.current = new AbortController();
    stopped.current = false;
    let failure: unknown = null;
    try {
      for await (const event of askChat({ ...request, memory }, controller.current.signal)) {
        const next = applyEvent(state, event);
        state = next.pending;
        if (next.memory) memory = next.memory;
        if (next.suggestion) setSuggestion(next.suggestion);
        setPending(state);
      }
    } catch (error) {
      if ((error as Error).name === "AbortError" && !stopped.current) return;
      failure = error;
    }
    const answer = finish(state, stopped.current ? STOPPED : failureMessage(failure, FAILED));
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

  useEffect(() => {
    if (pending || !typed.current) return;
    typed.current = false;
    box.current?.focus();
  }, [pending]);

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
        <div className="flex-1 space-y-4 pb-4" aria-label="대화">
          {messages.length === 0 && !pending ? (
            <p className="rounded-xl bg-accent/5 p-4 text-muted">
              반려견의 증상, 가까운 병원, 반려동물 관련 보고서 내용을 물어보세요. 응급 징후가 보이면 답보다 먼저 알려 드립니다.
            </p>
          ) : null}
          {/* Below the greeting, not above the conversation: it is known only once the browser's records
              are read, and above it pushed the whole conversation down (CLS 0.12, Lighthouse 2026-10-23). */}
          {notice ? (
            <p role="note" className="rounded-xl border border-accent/30 bg-accent/5 p-3 text-sm">
              {STORAGE_NOTICE}
            </p>
          ) : null}
          {messages.map((message, index) => (
            // Keyed by thread too: a 👍 chosen in one conversation must not show in another.
            <Bubble key={`${current ?? "new"}-${index}`} role={message.role}>
              {message.role === "user" ? (
                <p className="whitespace-pre-wrap">{message.content}</p>
              ) : (
                <AnswerView
                  answer={message}
                  question={askedBefore(messages, index)}
                  consultation={consultationFrom(messages, index)}
                  threadId={current}
                  onNoteSaved={() => setNotesVersion((v) => v + 1)}
                  onLocated={located}
                  // The last answer only, when it failed (not a question-limit notice: retrying would not help).
                  onRetry={message.notice === "error" && index === messages.length - 1 && !pending ? () => retry(index) : undefined}
                />
              )}
            </Bubble>
          ))}
          {pending ? (
            <Bubble role="assistant">
              <PendingView pending={pending} onStop={stop} onLocated={located} />
            </Bubble>
          ) : null}
          {suggestion && !pending ? <MemoryCard suggestion={suggestion} onSave={() => answerSuggestion(true)} onDismiss={() => answerSuggestion(false)} /> : null}
          <div ref={bottom} />
        </div>
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <button type="button" onClick={useLocation} className="rounded-lg border border-line bg-white px-3 py-1">
            <Icon name="locate" size={16} className="mr-1 inline-block align-[-3px]" />{location ? "위치 다시 가져오기" : "현재 위치 사용"}
          </button>
          <span className="text-muted">{locationNote ?? "가까운 병원 검색은 위치 사용을 선택한 경우에만 직선거리로 계산합니다."}</span>
        </div>
        <form onSubmit={submit} className="sticky bottom-[calc(4rem+env(safe-area-inset-bottom))] flex gap-2 border-t border-line bg-page py-3 md:bottom-0">
          <label htmlFor="question" className="sr-only">
            질문
          </label>
          <textarea
            ref={box}
            id="question"
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
                // Only a question that will go: an empty Enter must not pull the focus back later.
                typed.current = Boolean(draft.trim());
                submit(event);
              }
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
