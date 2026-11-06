import type { Metadata } from "next";

import Chat from "@/components/Chat";
import PageHeader from "@/components/PageHeader";

export const metadata: Metadata = { title: "건강 상담 · 라그도그" };

export default function ChatPage() {
  return (
    <main id="main" tabIndex={-1} className="mx-auto flex min-h-[calc(100dvh-3rem)] w-full max-w-5xl flex-col px-4">
      <PageHeader eyebrow="반려견 건강 상담" title="건강 상담" description="수의사 상담 기록을 근거로 답해요. 진료를 대신하지 않아요." />
      <Chat />
    </main>
  );
}
