import type { Metadata } from "next";

import Chat from "@/components/Chat";
import PageHeader from "@/components/PageHeader";

export const metadata: Metadata = { title: "질병 문의 · 라그도그" };

export default function ChatPage() {
  return (
    <main id="main" tabIndex={-1} className="mx-auto flex min-h-[calc(100dvh-3rem)] w-full max-w-5xl flex-col px-4">
      <PageHeader eyebrow="반려동물 건강 정보" title="반려견 AI 상담" description="수의사 상담 자료와 공공 데이터를 근거로 답합니다. 진료를 대신하지 않습니다." />
      <Chat />
    </main>
  );
}
