import type { Metadata } from "next";
import { Suspense } from "react";

import PageHeader from "@/components/PageHeader";
import Places from "@/components/Places";
import { kinds, regions } from "@/lib/places";
import { prefetched } from "@/lib/prefetch";

export const metadata: Metadata = { title: "시설 찾기 · 라그도그" };
export const revalidate = 86400; // a day: the kinds and regions change only with a data release

export default async function PlacesPage() {
  const initial = await prefetched(async () => {
    const [k, r] = await Promise.all([kinds(), regions()]);
    return { kinds: k, regions: r };
  });
  return (
    <main id="main" tabIndex={-1} className="mx-auto w-full max-w-5xl px-4 pb-12">
      <PageHeader
        eyebrow="가까운 반려동물 시설 찾기"
        title="반려동물 시설 찾기"
        description="동물병원, 동물약국, 반려견과 함께 갈 수 있는 곳, 미용·위탁·장묘업체를 지역이나 현재 위치로 찾아볼 수 있습니다."
      />
      {/* The ?id= of one place is read in the browser. */}
      <Suspense>
        <Places initial={initial} />
      </Suspense>
    </main>
  );
}
