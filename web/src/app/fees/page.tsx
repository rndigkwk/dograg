import type { Metadata } from "next";

import FeeExplorer from "@/components/FeeExplorer";
import PageHeader from "@/components/PageHeader";
import { DEFAULT_ITEM, feeItems, itemFees } from "@/lib/fees";
import { prefetched } from "@/lib/prefetch";

export const metadata: Metadata = { title: "지역별 진료비 · 라그도그" };
export const revalidate = 86400; // a day: the survey is yearly

export default async function FeesPage() {
  // The item list and the first item's figures (what the page shows before a choice).
  const initial = await prefetched(async () => {
    const { items } = await feeItems();
    const first = items.find((item) => item.label === DEFAULT_ITEM) ?? items[0];
    return { items, fees: await itemFees(first) };
  });
  return (
    <main id="main" tabIndex={-1} className="mx-auto w-full max-w-5xl px-4 pb-12">
      <PageHeader
        eyebrow="2025 동물병원 진료비 조사"
        title="지역별 진료비"
        description="진찰료·예방접종·검사·입원비가 우리 지역에서 보통 얼마인지, 전국과 비교해 확인하세요."
      />
      <FeeExplorer initial={initial} />
    </main>
  );
}
