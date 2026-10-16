import type { Metadata } from "next";

import PageHeader from "@/components/PageHeader";
import VisitPrep from "@/components/VisitPrep";

export const metadata: Metadata = { title: "방문 준비 보고서 · 라그도그" };

export default function VisitPrepPage() {
  return (
    <main className="mx-auto w-full max-w-3xl px-4 pb-12">
      <PageHeader
        eyebrow="멀티에이전트 팀"
        title="병원 방문 준비 보고서"
        description="상담 내용을 증상·병원·비용 조사로 나눠 여러 에이전트가 동시에 조사하고, 작성자가 쓴 보고서를 검수자가 문장마다 근거와 대조합니다. 진단이 아니라 수의사에게 보여 줄 정리입니다."
      />
      <VisitPrep />
    </main>
  );
}
