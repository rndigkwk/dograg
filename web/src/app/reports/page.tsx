import type { Metadata } from "next";

import PageHeader from "@/components/PageHeader";
import ReportAsk from "@/components/ReportAsk";

export const metadata: Metadata = { title: "보고서 분석 · 라그도그" };

export default function ReportsPage() {
  return (
    <main className="mx-auto w-full max-w-5xl px-4 pb-12">
      <PageHeader
        eyebrow="반려동물 보고서 5종"
        title="보고서 분석"
        description="KB·한국농촌경제연구원·한국소비자원의 반려동물 보고서에서 수치를 찾아, 근거 쪽수와 함께 정리해 드립니다."
      />
      <ReportAsk />
    </main>
  );
}
