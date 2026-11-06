"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { loadPlanned, loadRecord, nextCare } from "@/lib/careSchedule";
import { askLater, MAX_QUESTION_CHARS } from "@/lib/chat";
import { describeAge, loadProfile, type PetProfile } from "@/lib/profile";
import { browserStorage } from "@/lib/store";

import Icon from "./Icon";

// The home page (2026-11-06 guardian-view mockup): the dog by name, one question box, and the
// situations guardians come with. A situation opens a few ready questions; 접종·예방 is the schedule.
type Situation = { title: string; sub: string; questions?: string[]; href?: string };

export const SITUATIONS: Situation[] = [
  { title: "아파 보여요", sub: "구토 · 설사 · 기운 없음", questions: ["구토를 해요", "설사를 해요", "기운이 없고 밥을 안 먹어요"] },
  { title: "다쳤어요", sub: "피 · 절뚝임 · 물림", questions: ["발톱이 부러져서 피가 나요", "다리를 절뚝거려요", "다른 개에게 물렸어요"] },
  { title: "뭘 먹었어요", sub: "초콜릿 · 포도 · 약", questions: ["초콜릿을 먹었어요", "포도를 먹었어요", "사람 약을 삼켰어요"] },
  { title: "피부 · 귀 · 눈", sub: "긁음 · 냄새 · 충혈", questions: ["몸을 자꾸 긁어요", "귀에서 냄새가 나요", "눈이 빨개요"] },
  { title: "접종 · 예방", sub: "다음 날짜 알려 드려요", href: "/care" },
  { title: "행동 · 생활", sub: "짖음 · 분리불안 · 산책", questions: ["계속 짖어요", "혼자 두면 울어요", "산책은 얼마나 해야 하나요?"] },
];

/** A name ready for 가/에게: 보리 → 보리(가), 콩 → 콩이(가), as Koreans call a dog with a final consonant. */
export function withSubject(name: string): string {
  const last = name.charCodeAt(name.length - 1);
  const hasBatchim = last >= 0xac00 && last <= 0xd7a3 && (last - 0xac00) % 28 !== 0;
  return `${name}${hasBatchim ? "이" : ""}`;
}

type Pet = { ready: boolean; profile: PetProfile | null; next: ReturnType<typeof nextCare> };

/** The dog and its next care date from this browser; `ready` once read (no "add your dog" flash first). */
function usePet(): Pet {
  const [state, setState] = useState<Pet>({ ready: false, profile: null, next: null });
  useEffect(() => {
    const storage = browserStorage();
    setState({ ready: true, profile: loadProfile(storage), next: nextCare(loadRecord(storage), loadPlanned(storage)) });
  }, []);
  return state;
}

function PetCard({ ready, profile, next }: Pet) {
  if (!ready) return null;
  if (!profile)
    return (
      <Link href="/chat#profile" className="flex items-center gap-3 rounded-2xl border border-dashed border-line bg-white p-4 hover:border-accent">
        <span className="inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-accent/10 text-accent">
          <Icon name="heart" size={20} />
        </span>
        <span className="text-sm">
          <strong className="block text-base">우리 아이 정보 넣기</strong>
          <span className="text-muted">이름·나이·체중을 넣으면 답과 진료비가 맞춰져요</span>
        </span>
      </Link>
    );
  const facts = [profile.birth_month ? describeAge(profile.birth_month).replace(/ \(.+\)$/, "") : null, profile.breed, profile.weight_kg ? `${profile.weight_kg}kg` : null].filter(Boolean);
  return (
    <section aria-label="우리 아이" className="rounded-2xl border border-line bg-white p-4">
      <div className="flex items-center gap-3">
        <span aria-hidden="true" className="inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-accent/10 font-bold text-accent">
          {(profile.name ?? "우")[0]}
        </span>
        <div className="min-w-0 flex-1">
          <p className="truncate font-bold">{profile.name ?? "우리 아이"}</p>
          {facts.length ? <p className="truncate text-sm text-muted">{facts.join(" · ")}</p> : null}
        </div>
        <Link href="/chat#profile" className="inline-flex min-h-11 items-center text-sm text-accent">
          바꾸기
        </Link>
      </div>
      {next ? (
        <p className="mt-3 flex justify-between gap-2 border-t border-line pt-3 text-sm">
          <span>{next.item.label}</span>
          <strong className={next.due.status === "overdue" || next.due.status === "due" ? "text-danger" : ""}>
            {next.due.days > 0 ? `${next.due.from.slice(5).replace("-", "월 ")}일 · ${next.due.days}일 뒤` : next.due.status === "overdue" ? "지났어요" : "지금 할 때예요"}
          </strong>
        </p>
      ) : null}
    </section>
  );
}

const SHORTCUTS = [
  { href: "/places", title: "가까운 동물병원 찾기" },
  { href: "/fees", title: "병원비 얼마 나올까?" },
  { href: "/visit-prep", title: "병원 가기 전 메모 만들기" },
];

export default function HomeStart() {
  const router = useRouter();
  const pet = usePet();
  const { profile } = pet;
  const [draft, setDraft] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const box = useRef<HTMLInputElement>(null);
  const name = profile?.name;

  function go(question: string) {
    // Storage blocked: the chat page opens with an empty box rather than the question in the URL.
    askLater(question);
    router.push("/chat");
  }

  const chosen = SITUATIONS.find((situation) => situation.title === open);
  return (
    <div className="grid gap-8 md:grid-cols-[minmax(0,1fr)_340px] md:items-start">
      <div className="space-y-7">
        <div className="md:hidden">
          <PetCard {...pet} />
        </div>
        <section className="space-y-4">
          <h1 className="text-2xl font-bold leading-snug md:text-4xl">{name ? `${withSubject(name)}에게` : "우리 아이에게"} 무슨 일이 있나요?</h1>
          <form
            onSubmit={(event) => {
              event.preventDefault();
              if (draft.trim()) go(draft);
            }}
            className="flex items-center gap-2 rounded-2xl border-2 border-accent bg-white p-2 pl-4"
          >
            <label htmlFor="home-question" className="sr-only">
              질문
            </label>
            <input
              id="home-question"
              ref={box}
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              maxLength={MAX_QUESTION_CHARS}
              placeholder="예: 이틀째 설사를 하는데 밥은 먹어요"
              className="min-w-0 flex-1 bg-transparent text-base text-ink placeholder:text-muted focus:outline-none md:text-lg"
            />
            <button type="submit" disabled={!draft.trim()} className="inline-flex min-h-12 items-center gap-1.5 rounded-xl bg-accent px-4 font-semibold text-white disabled:opacity-40 md:px-6">
              <span className="hidden sm:inline">질문하기</span>
              <Icon name="send" size={20} label="질문하기" className="sm:hidden" />
            </button>
          </form>
        </section>

        <section aria-labelledby="situations" className="space-y-3">
          <h2 id="situations" className="text-sm font-semibold text-muted md:text-base">
            이런 일이라면 바로 눌러 보세요
          </h2>
          <ul className="grid grid-cols-2 gap-3 md:grid-cols-3">
            {SITUATIONS.map((situation) => {
              const body = (
                <>
                  <span className="text-base font-bold md:text-lg">{situation.title}</span>
                  <span className="text-sm text-muted">{situation.sub}</span>
                </>
              );
              const style = "flex h-full min-h-20 w-full flex-col items-start gap-1 rounded-2xl border bg-white p-4 text-left transition hover:border-accent md:min-h-24 md:p-5";
              return (
                <li key={situation.title}>
                  {situation.href ? (
                    <Link href={situation.href} className={`${style} border-line`}>
                      {body}
                    </Link>
                  ) : (
                    <button
                      type="button"
                      aria-expanded={open === situation.title}
                      aria-controls="situation-questions"
                      onClick={() => setOpen(open === situation.title ? null : situation.title)}
                      className={`${style} ${open === situation.title ? "border-accent ring-1 ring-accent" : "border-line"}`}
                    >
                      {body}
                    </button>
                  )}
                </li>
              );
            })}
          </ul>
          {chosen?.questions ? (
            <div id="situation-questions" className="rounded-2xl border border-line bg-white p-4">
              <p className="mb-2 text-sm text-muted">이 중에 비슷한 게 있으면 눌러 보세요. 아니면 위 칸에 자세히 적어 주세요.</p>
              <ul aria-label={`${chosen.title} 예시 질문`} className="flex flex-wrap gap-2">
                {chosen.questions.map((question) => (
                  <li key={question}>
                    <button type="button" onClick={() => go(name ? `${withSubject(name)}가 ${question}` : question)} className="min-h-10 rounded-full border border-accent px-4 text-sm text-accent hover:bg-accent/5">
                      {question}
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </section>

        <p className="text-xs text-muted">
          수의사 상담 기록 19,206건과 공공 돌봄 지침을 바탕으로 안내하며 진료를 대신하지 않아요.{" "}
          <Link href="/data" className="text-accent underline">
            어떻게 답하나요?
          </Link>
        </p>
      </div>

      <aside className="space-y-4">
        <div className="hidden md:block">
          <PetCard {...pet} />
        </div>
        <nav aria-labelledby="shortcuts" className="space-y-2">
          <h2 id="shortcuts" className="text-sm font-semibold text-muted md:text-base">
            가까운 곳 · 비용
          </h2>
          {SHORTCUTS.map((item) => (
            <Link key={item.href} href={item.href} className="flex min-h-14 items-center justify-between rounded-2xl border border-line bg-white px-4 hover:border-accent">
              {item.title}
              <span aria-hidden="true">›</span>
            </Link>
          ))}
        </nav>
        <Link href="/demo" className="block text-sm font-semibold text-accent underline">
          처음이라면 예시로 2분 둘러보기 →
        </Link>
      </aside>
    </div>
  );
}
