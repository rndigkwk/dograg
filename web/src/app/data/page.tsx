import type { Metadata } from "next";

import DataOverview from "@/components/DataOverview";
import PageHeader from "@/components/PageHeader";
import { prefetched } from "@/lib/prefetch";
import { overview } from "@/lib/stats";

export const metadata: Metadata = { title: "소개 · 라그도그" };
export const revalidate = 86400; // a day: the counts change only with a data release

export default async function DataPage() {
  const initial = await prefetched(overview);
  return (
    <main id="main" tabIndex={-1} className="mx-auto w-full max-w-5xl px-4 pb-12">
      <PageHeader eyebrow="프로젝트와 데이터" title="라그도그 소개" description="라그도그가 무엇이고 어떻게 만들었는지, 답과 목록이 어떤 데이터에서 나오는지 확인하세요." />
      <DataOverview initial={initial} />
    </main>
  );
}
