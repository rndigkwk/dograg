"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

// The Streamlit app's pages (src/ui.py NAVIGATION_GROUPS), added here as each one moves (ADR-0008 P3).
const LINKS = [
  { href: "/data", label: "📊 데이터 소개" },
  { href: "/chat", label: "💬 질병 문의" },
  { href: "/places", label: "🏥 시설 찾기" },
];

export default function NavBar() {
  const path = usePathname();
  return (
    <nav aria-label="메뉴" className="border-b border-line bg-white">
      <div className="mx-auto flex max-w-5xl items-center gap-1 overflow-x-auto px-4 py-2 text-sm">
        <Link href="/" className="mr-3 shrink-0 font-bold text-accent">
          🐾 라그도그
        </Link>
        {LINKS.map((link) => {
          const active = path === link.href || path.startsWith(`${link.href}/`);
          return (
            <Link
              key={link.href}
              href={link.href}
              aria-current={active ? "page" : undefined}
              className={`shrink-0 rounded-lg px-3 py-1.5 ${active ? "bg-accent/10 font-semibold text-accent" : "text-ink hover:bg-line/50"}`}
            >
              {link.label}
            </Link>
          );
        })}
      </div>
    </nav>
  );
}
