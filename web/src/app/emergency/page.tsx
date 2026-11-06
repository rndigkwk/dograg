import type { Metadata } from "next";
import Link from "next/link";

import EmergencyHelp from "@/components/EmergencyHelp";

export const metadata: Metadata = { title: "응급이에요 · 라그도그" };

// The header's red button (2026-11-06 guardian-view mockup). The signs are the groups the app's own
// urgent-sign rules look for (src/health_safety.py URGENT_PATTERNS), in a guardian's words.
const SIGNS = [
  "숨을 잘 못 쉬거나 혀·잇몸이 파랗거나 하얘요",
  "쓰러졌거나 의식이 없고 일어나지 못해요",
  "발작·경련을 하거나 거품을 물어요",
  "초콜릿·포도·자일리톨·사람 약·쥐약 같은 것을 먹었어요",
  "배가 부풀고 토하려 해도 아무것도 안 나와요",
  "피가 멈추지 않거나 피 섞인 토·설사가 계속돼요",
  "차에 치였거나 깊게 물렸어요",
  "더운 곳에서 축 늘어졌어요(열사병)",
  "소변을 전혀 못 봐요",
];

export default function EmergencyPage() {
  return (
    <main id="main" tabIndex={-1} className="mx-auto w-full max-w-3xl space-y-6 px-4 py-6 md:py-10">
      <header className="space-y-2">
        <h1 className="text-2xl font-bold text-danger md:text-3xl">지금 바로 동물병원에 연락하세요</h1>
        <p className="text-muted">아래 중 하나라도 있으면 답을 기다리지 말고 가까운 동물병원에 전화한 뒤 출발하세요.</p>
      </header>

      <section aria-labelledby="signs" className="rounded-2xl border border-danger/30 bg-danger/5 p-4 md:p-5">
        <h2 id="signs" className="mb-2 font-bold">바로 병원에 가야 할 때</h2>
        <ul className="list-disc space-y-1 pl-5">
          {SIGNS.map((sign) => (
            <li key={sign}>{sign}</li>
          ))}
        </ul>
      </section>

      <section aria-labelledby="nearest" className="rounded-2xl border border-line bg-white p-4 md:p-5">
        <h2 id="nearest" className="mb-1 font-bold">가까운 동물병원</h2>
        <EmergencyHelp />
      </section>

      <p className="text-sm text-muted">
        급하지 않은 것 같다면 <Link href="/chat" className="text-accent underline">건강 상담</Link>에서 증상을 적어 물어보세요. 온라인 안내는 진단이 아닙니다.
      </p>
    </main>
  );
}
