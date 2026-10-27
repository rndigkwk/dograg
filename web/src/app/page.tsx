import type { Metadata } from "next";
import Link from "next/link";

import HeroImage from "@/components/HeroImage";
import HomeAsk from "@/components/HomeAsk";
import Icon, { type IconName } from "@/components/Icon";

// Design A (2026-10-24): the question first, then the four things guardians come back for. The
// place count is the facility database's (docs/wiki/places-data.md); the rest is on /data.
const SHORTCUTS: { href: string; icon: IconName; title: string; body: string }[] = [
  { href: "/places", icon: "pin", title: "시설 찾기", body: "동물병원·약국부터 동반 카페·미용까지 38,529곳" },
  { href: "/fees", icon: "receipt", title: "지역별 진료비", body: "우리 동네 중간값을 전국과 비교" },
  { href: "/care", icon: "calendar", title: "관리 일정", body: "접종·구충·예방의 다음 날짜" },
  { href: "/visit-prep", icon: "file", title: "방문 준비 보고서", body: "증상과 질문을 정리해 진료에 가져가기" },
];

export const metadata: Metadata = { title: "라그도그 · 반려동물 건강 정보" };

export default function Home() {
  return (
    <main id="main" tabIndex={-1} className="mx-auto w-full max-w-5xl space-y-8 px-4 py-8 md:py-12">
      <section className="grid items-center gap-8 md:grid-cols-[1.15fr_0.85fr]">
        <div className="space-y-4">
          <p className="text-sm font-semibold text-accent">반려견 건강 상담</p>
          <h1 className="text-2xl font-bold leading-snug md:text-4xl">
            어떤 점이 걱정되세요?
            <span className="mt-1 block text-lg font-semibold text-muted md:text-2xl">수의사 상담 기록에서 찾아 드릴게요.</span>
          </h1>
          <HomeAsk />
          <p className="text-sm text-muted">
            수의사 상담 19,206건과 공공 돌봄 지침을 근거로 답합니다. 응급 신호가 보이면 답보다 먼저 알려 드립니다. 진료를 대신하지 않습니다.
          </p>
          <Link href="/demo" className="inline-block text-sm font-semibold text-accent underline">
            처음이라면 예시로 2분 둘러보기 →
          </Link>
        </div>
        {/* The photo is for wide screens: on a phone the question box and the shortcuts come first. */}
        <div className="hidden md:block">
          <HeroImage />
        </div>
      </section>

      <section aria-labelledby="shortcuts">
        <h2 id="shortcuts" className="sr-only">
          바로 가기
        </h2>
        <ul className="grid grid-cols-2 gap-3 md:grid-cols-4 md:gap-4">
          {SHORTCUTS.map((item) => (
            <li key={item.href}>
              <Link href={item.href} className="flex h-full flex-col gap-2 rounded-2xl border border-line bg-white p-4 transition hover:border-accent md:p-5">
                <Icon name={item.icon} size={24} className="text-accent" />
                <span className="font-bold">{item.title}</span>
                <span className="text-sm text-muted">{item.body}</span>
              </Link>
            </li>
          ))}
        </ul>
      </section>

      <p className="text-xs text-muted">
        프로젝트 설명과 상담·시설 데이터, 데이터 출처는{" "}
        <Link href="/data" className="text-accent underline">
          프로젝트·데이터 소개
        </Link>
        에서 볼 수 있습니다.
      </p>
    </main>
  );
}
