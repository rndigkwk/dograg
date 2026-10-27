import type { Metadata } from "next";
import Link from "next/link";

import { AnswerView } from "@/components/ChatMessages";
import Markdown from "@/components/Markdown";
import PageHeader from "@/components/PageHeader";
import type { Answer } from "@/lib/chat";
import sample from "@/lib/demoSample.json";

export const metadata: Metadata = { title: "예시로 둘러보기 · 라그도그" };

// Saved output of the real pipeline, not written by hand: the two answers from src/chatbot.py
// (2026-10-27) and a visit-prep report the team made and the reviewer passed (2026-10-19). The page
// calls no model and keeps nothing; the dog is made up.
const health = sample.health.answer as Answer;
const abstain = sample.abstain.answer as Answer;

function Step({ number, title, children }: { number: number; title: string; children: React.ReactNode }) {
  return (
    <section aria-labelledby={`step-${number}`} className="space-y-3">
      <h2 id={`step-${number}`} className="text-lg font-bold">
        <span className="mr-2 text-accent">{number}</span>
        {title}
      </h2>
      {children}
    </section>
  );
}

function Bubble({ text }: { text: string }) {
  return <p className="ml-auto w-fit max-w-[85%] rounded-2xl bg-accent px-4 py-2 text-white">{text}</p>;
}

function Card({ children }: { children: React.ReactNode }) {
  return <div className="rounded-2xl border border-line bg-white p-4">{children}</div>;
}

export default function DemoPage() {
  return (
    <main id="main" tabIndex={-1} className="mx-auto w-full max-w-3xl space-y-8 px-4 pb-12">
      <PageHeader
        eyebrow="예시"
        title="예시로 둘러보기"
        description="가상의 14살 말티즈 한 마리로 상담부터 방문 준비 보고서까지 보여 드립니다. 서비스가 실제로 만든 답과 보고서를 저장해 둔 것이라, 이 페이지는 모델을 부르지 않고 아무것도 저장하지 않습니다."
      />

      <p role="note" className="rounded-lg bg-warn/10 p-3 text-sm">
        <strong>예시 화면입니다.</strong> 실제 상담이 아니고, 아래 반려견은 가상입니다. 직접 물어보려면{" "}
        <Link href="/chat" className="text-accent underline">
          상담
        </Link>
        에서 시작하세요.
      </p>

      <Step number={1} title="증상을 물으면 상담 사례를 근거로 답합니다">
        <Bubble text={sample.health.question} />
        <Card>
          <AnswerView answer={health} />
        </Card>
        <p className="text-sm text-muted">
          [사례 1]을 누르면 근거가 된 수의사 상담 카드가 열립니다. 자료에 없는 부분(밤에 서성임, 식욕)은 없다고 밝힙니다.
        </p>
      </Step>

      <Step number={2} title="근거가 없으면 답하지 않습니다">
        <Bubble text={sample.abstain.question} />
        <Card>
          <AnswerView answer={abstain} />
        </Card>
        <p className="text-sm text-muted">무엇을 찾아봤고 무엇을 확인하지 못했는지 함께 보여 줍니다.</p>
      </Step>

      <Step number={3} title="병원에 가기 전에 보고서로 정리합니다">
        <p className="text-sm text-muted">
          상담 내용: “{sample.report.consultation}” · 지역: {sample.report.region}. 여러 에이전트가 증상·병원을 나눠 조사하고,
          검수자가 문장 {sample.report.supported}개를 근거와 대조해 통과시킨 보고서입니다.
        </p>
        <Card>
          <Markdown text={sample.report.text} />
        </Card>
      </Step>

      <section aria-labelledby="next" className="space-y-2">
        <h2 id="next" className="text-lg font-bold">
          직접 해 보기
        </h2>
        <ul className="grid grid-cols-2 gap-3 text-sm md:grid-cols-4">
          {[
            { href: "/chat", label: "상담하기" },
            { href: "/visit-prep", label: "방문 준비 보고서" },
            { href: "/care", label: "관리 일정" },
            { href: "/fees", label: "지역별 진료비" },
          ].map((item) => (
            <li key={item.href}>
              <Link href={item.href} className="block rounded-xl border border-line bg-white p-3 text-center font-semibold hover:border-accent">
                {item.label}
              </Link>
            </li>
          ))}
        </ul>
      </section>
    </main>
  );
}
