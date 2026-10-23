"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { askLater, MAX_QUESTION_CHARS } from "@/lib/chat";

import Icon from "./Icon";

// Questions the app answers well (the deployment check and the evaluation sets ask the same kinds).
const EXAMPLES = ["발톱이 부러져서 피가 나요", "강남구 동물병원 알려줘", "중성화 수술 비용이 궁금해요"];

/** The home page's question box (design A): the question goes to the chat page, which asks it. */
export default function HomeAsk() {
  const router = useRouter();
  const [draft, setDraft] = useState("");

  function go(question: string) {
    // Storage blocked: the chat page opens with an empty box rather than the question in the URL.
    askLater(question);
    router.push("/chat");
  }

  return (
    <div className="space-y-3">
      <form
        onSubmit={(event) => {
          event.preventDefault();
          if (draft.trim()) go(draft);
        }}
        className="flex items-center gap-2 rounded-2xl border border-[#79948e] bg-white p-2 pl-4 focus-within:border-accent"
      >
        <label htmlFor="home-question" className="sr-only">
          질문
        </label>
        <input
          id="home-question"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          maxLength={MAX_QUESTION_CHARS}
          placeholder="예: 3살 말티즈가 이틀째 설사를 해요"
          className="min-w-0 flex-1 bg-transparent text-base text-ink placeholder:text-muted focus:outline-none"
        />
        <button
          type="submit"
          disabled={!draft.trim()}
          className="inline-flex min-h-12 items-center gap-1.5 rounded-xl bg-accent px-4 font-semibold text-white disabled:opacity-40"
        >
          <span className="hidden sm:inline">질문하기</span>
          <Icon name="send" size={20} label="질문하기" className="sm:hidden" />
        </button>
      </form>
      <ul aria-label="예시 질문" className="flex flex-wrap gap-2">
        {EXAMPLES.map((example) => (
          <li key={example}>
            <button type="button" onClick={() => go(example)} className="min-h-9 rounded-full border border-line bg-white px-3 text-sm text-[#2e4a44] hover:border-accent">
              {example}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
