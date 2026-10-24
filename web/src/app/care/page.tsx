import type { Metadata } from "next";

import CareSchedule from "@/components/CareSchedule";
import PageHeader from "@/components/PageHeader";

export const metadata: Metadata = { title: "관리 일정 · 라그도그" };

export default function CarePage() {
  return (
    <main id="main" tabIndex={-1} className="mx-auto w-full max-w-3xl px-4 pb-12">
      <PageHeader eyebrow="우리 아이 관리" title="관리 일정"
        description="예방약·구충·추가접종·검진·발톱 손질을 마지막으로 한 날을 적으면, 공공 돌봄 지침의 주기로 다음 날짜를 알려 드립니다." />
      <CareSchedule />
    </main>
  );
}
