import type { Metadata } from "next";

import NotesManager from "@/components/NotesManager";
import PageHeader from "@/components/PageHeader";

export const metadata: Metadata = { title: "지난 상담 기억 · 라그도그" };

export default function MemoryPage() {
  return (
    <main id="main" tabIndex={-1} className="mx-auto w-full max-w-3xl px-4 pb-12">
      <PageHeader eyebrow="내 계정" title="지난 상담 기억" description="저장한 상담 기록을 보고 지우거나, 새 질문에 쓸지 정합니다. 기록은 내 계정에만 있고 나만 볼 수 있습니다." />
      <NotesManager />
    </main>
  );
}
