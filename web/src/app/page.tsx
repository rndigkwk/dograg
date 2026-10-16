import type { Metadata } from "next";
import Link from "next/link";

import HeroImage from "@/components/HeroImage";

// The Streamlit home page (app_pages/home.py, src/ui.py HOME_STATS). Source: KB경영연구소.
const STATS = [
  { label: "반려동물 가구", value: "591만 가구", detail: "전체 가구 중 26.7%" },
  { label: "반려견", value: "546만 마리", detail: "건강 정보가 필요한 가족" },
];

const SERVICES = [
  { href: "/chat", icon: "💬", title: "질병 문의", body: "반려견의 증상과 질병에 대해 근거 있는 정보를 확인해보세요." },
  { href: "/places", icon: "📍", title: "반려동물 시설 찾기", body: "동물병원·약국부터 반려견 동반 카페·펜션, 미용·위탁 업체까지 내 주변에서 찾아보세요." },
  { href: "/visit-prep", icon: "📝", title: "방문 준비 보고서", body: "상담 내용을 정리해 병원에서 수의사에게 보여 줄 보고서를 만들어보세요." },
  { href: "/data", icon: "📊", title: "데이터 소개", body: "상담 데이터와 반려동물 시설 데이터를 한눈에 살펴보세요." },
];

export const metadata: Metadata = { title: "라그도그 · 반려동물 건강 정보" };

const CHIPS = ["◷ 신뢰할 수 있는 데이터", "⌖ 지역 기반 맞춤 정보", "✦ 빠르고 쉬운 접근"];

export default function Home() {
  return (
    <main className="mx-auto w-full max-w-5xl space-y-10 px-4 py-8">
      <section className="grid items-center gap-8 md:grid-cols-[1.08fr_0.92fr]">
        <div className="space-y-4">
          <p className="text-sm font-semibold text-accent">● 반려동물 건강 정보 플랫폼</p>
          <h1 className="text-3xl font-extrabold leading-tight md:text-4xl">
            반려동물의 건강,
            <br />
            데이터로 지키는 <span className="text-accent">따뜻한 동행</span>
          </h1>
          <p className="text-muted">
            라그도그는 반려견 보호자가 건강 정보를 찾고 가까운 동물 병원을 확인할 수 있도록 돕는 데이터 기반 반려동물 케어 서비스입니다. 591만 반려동물
            가구 시대, 필요한 정보를 더 빠르게 확인해보세요.
          </p>
          <ul className="flex flex-wrap gap-2 text-sm" aria-label="특징">
            {CHIPS.map((chip) => (
              <li key={chip} className="rounded-full border border-line bg-white px-3 py-1">
                {chip}
              </li>
            ))}
          </ul>
          <Link href="/chat" className="inline-block rounded-xl bg-accent px-5 py-3 font-semibold text-white">
            💬 지금 질문하기
          </Link>
        </div>
        <HeroImage />
      </section>

      <section aria-label="반려동물 현황" className="grid gap-4 sm:grid-cols-2">
        {STATS.map((stat) => (
          <div key={stat.label} className="rounded-2xl border border-line bg-white p-5">
            <p className="text-sm text-muted">{stat.label}</p>
            <p className="mt-1 text-2xl font-bold">{stat.value}</p>
            <p className="text-sm text-muted">{stat.detail}</p>
          </div>
        ))}
      </section>

      <section aria-labelledby="services" className="space-y-4">
        <h2 id="services" className="text-xl font-bold">
          주요 서비스
        </h2>
        <ul className="grid gap-4 sm:grid-cols-2">
          {SERVICES.map((service) => (
            <li key={service.href}>
              <Link href={service.href} className="block h-full rounded-2xl border border-line bg-white p-5 transition hover:border-accent">
                <span className="text-2xl" aria-hidden>
                  {service.icon}
                </span>
                <span className="mt-2 block font-bold">{service.title}</span>
                <span className="mt-1 block text-sm text-muted">{service.body}</span>
              </Link>
            </li>
          ))}
        </ul>
        <p className="text-xs text-muted">자료 출처: KB경영연구소 · 위 메뉴에서 원하는 화면을 선택해 자세한 정보를 확인해보세요.</p>
      </section>
    </main>
  );
}
