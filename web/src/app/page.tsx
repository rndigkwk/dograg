import type { Metadata } from "next";

import HomeStart from "@/components/HomeStart";

export const metadata: Metadata = { title: "라그도그 · 반려동물 건강 정보" };

// 2026-11-06 guardian-view mockup: the dog by name and the situations guardians come with, not the
// app's features. The project and data are on /data.
export default function Home() {
  return (
    <main id="main" tabIndex={-1} className="mx-auto w-full max-w-5xl px-4 py-6 md:py-10">
      <HomeStart />
    </main>
  );
}
