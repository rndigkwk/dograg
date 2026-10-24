// The menu (design A, 2026-10-24): ten top-level links became four groups. One table feeds the
// desktop menus, the phone's bottom tabs and the group's tab row on each page.

import type { IconName } from "@/components/Icon";

/** `signedOut`: a word next to the page in the menu when signed out, where its records live then. */
export type NavPage = { href: string; label: string; icon: IconName; signedOut?: string };
export type NavGroup = { id: string; label: string; icon: IconName; pages: NavPage[] };

export const GROUPS: NavGroup[] = [
  {
    id: "ask",
    label: "상담",
    icon: "chat",
    pages: [
      { href: "/chat", label: "질병 문의", icon: "chat" },
      { href: "/visit-prep", label: "방문 준비 보고서", icon: "file" },
      { href: "/reports", label: "보고서 질문", icon: "book" },
    ],
  },
  {
    id: "find",
    label: "찾기",
    icon: "pin",
    pages: [
      { href: "/places", label: "시설 찾기", icon: "pin" },
      { href: "/fees", label: "지역별 진료비", icon: "receipt" },
    ],
  },
  {
    id: "mine",
    label: "우리 아이",
    icon: "heart",
    pages: [
      { href: "/care", label: "관리 일정", icon: "calendar", signedOut: "이 기기" },
      { href: "/memory", label: "상담 기억", icon: "note", signedOut: "로그인 필요" },
    ],
  },
  { id: "about", label: "소개", icon: "chart", pages: [{ href: "/data", label: "데이터 소개", icon: "chart" }] },
];

export function isOn(path: string, href: string): boolean {
  return path === href || path.startsWith(`${href}/`);
}

/** The group the page at `path` belongs to (none on the home page). */
export function groupOf(path: string): NavGroup | undefined {
  return GROUPS.find((group) => group.pages.some((page) => isOn(path, page.href)));
}
