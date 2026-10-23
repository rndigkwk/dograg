import type { Metadata } from "next";

import DataOverview from "@/components/DataOverview";
import PageHeader from "@/components/PageHeader";
import { prefetched } from "@/lib/prefetch";
import { overview } from "@/lib/stats";

export const metadata: Metadata = { title: "데이터 소개 · 라그도그" };
export const revalidate = 86400; // a day: the counts change only with a data release

export default async function DataPage() {
  const initial = await prefetched(overview);
  return (
    <main className="mx-auto w-full max-w-5xl px-4 pb-12">
      <PageHeader eyebrow="신뢰할 수 있는 데이터" title="데이터 소개" description="반려동물 건강과 동물병원 데이터를 한눈에 확인하고, 필요한 인사이트를 찾아보세요." />
      <DataOverview initial={initial} />
    </main>
  );
}
