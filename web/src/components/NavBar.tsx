"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { GROUPS, groupOf, isOn, type NavGroup, type NavPage } from "@/lib/nav";

import AccountButton from "./AccountButton";
import { useAuth } from "./AuthProvider";
import Icon from "./Icon";

/** Where a page's records live when signed out (lib/nav.ts `signedOut`); nothing once signed in or before
 * the session is known (no flash for a signed-in guardian). */
function SignedOutHint({ page }: { page: NavPage }) {
  const { session, ready } = useAuth();
  if (!page.signedOut || !ready || session) return null;
  return <span className="ml-auto pl-2 text-xs font-normal text-muted">{page.signedOut}</span>;
}

/** A desktop group with several pages: a button that opens its list (closes on a pick, Escape, a click
 * outside or Tab past its last page; Escape puts the focus back on the button). */
function GroupMenu({ group, active }: { group: NavGroup; active: boolean }) {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  const path = usePathname();

  useEffect(() => setOpen(false), [path]);
  useEffect(() => {
    if (!open) return;
    const outside = (event: MouseEvent) => {
      if (!box.current?.contains(event.target as Node)) setOpen(false);
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setOpen(false);
      if (box.current?.contains(document.activeElement)) button.current?.focus();
    };
    document.addEventListener("mousedown", outside);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("mousedown", outside);
      document.removeEventListener("keydown", escape);
    };
  }, [open]);

  return (
    <div
      ref={box}
      className="relative"
      onBlur={(event) => {
        // Only when the focus moved to another control: a click that focuses nothing (Safari on a link)
        // must not close the list before the link is followed; clicks outside close it above.
        const next = event.relatedTarget as Node | null;
        if (next && !box.current?.contains(next)) setOpen(false);
      }}
    >
      <button
        ref={button}
        type="button"
        aria-expanded={open}
        aria-controls={`menu-${group.id}`}
        onClick={() => setOpen((shown) => !shown)}
        className={`inline-flex min-h-11 items-center gap-1 rounded-lg px-3 ${active ? "bg-accent/10 font-semibold text-accent" : "text-ink hover:bg-line/50"}`}
      >
        {group.label}
        <Icon name="chevronDown" size={16} className={open ? "rotate-180" : ""} />
      </button>
      {open ? (
        <ul id={`menu-${group.id}`} className="absolute left-0 top-12 z-20 w-60 space-y-1 rounded-xl border border-line bg-white p-2 shadow-lg">
          {group.pages.map((page) => (
            <li key={page.href}>
              <Link
                href={page.href}
                aria-current={isOn(path, page.href) ? "page" : undefined}
                className={`flex min-h-11 items-center gap-2 rounded-lg px-3 ${isOn(path, page.href) ? "bg-accent/10 font-semibold text-accent" : "text-ink hover:bg-page"}`}
              >
                <Icon name={page.icon} size={18} />
                {page.label}
                <SignedOutHint page={page} />
              </Link>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

const HOME_TAB = { id: "home", label: "홈", icon: "home" as const, href: "/" };

/** The menu (design A, 2026-10-24; lib/nav.ts): four groups across the top on a wide screen, tabs at the
 * bottom on a phone, and the current group's pages as a tab row under the bar. */
export default function NavBar() {
  const path = usePathname();
  const current = groupOf(path);
  const tabs = [HOME_TAB, ...GROUPS.slice(0, 3).map((group) => ({ id: group.id, label: group.label, icon: group.icon, href: group.pages[0].href }))];
  return (
    <>
      <header className="border-b border-line bg-white">
        <div className="mx-auto flex max-w-5xl items-center gap-2 px-4 py-2 text-sm">
          <Link href="/" className="mr-2 flex shrink-0 items-center gap-2 text-base font-bold text-ink">
            <span className="inline-flex h-7 w-7 items-center justify-center rounded-lg bg-accent text-white">
              <Icon name="heart" size={16} />
            </span>
            라그도그
          </Link>
          <nav aria-label="메뉴" className="hidden flex-1 items-center gap-1 md:flex">
            {GROUPS.map((group) =>
              group.pages.length > 1 ? (
                <GroupMenu key={group.id} group={group} active={current?.id === group.id} />
              ) : (
                <Link
                  key={group.id}
                  href={group.pages[0].href}
                  aria-current={current?.id === group.id ? "page" : undefined}
                  className={`inline-flex min-h-11 items-center rounded-lg px-3 ${current?.id === group.id ? "bg-accent/10 font-semibold text-accent" : "text-ink hover:bg-line/50"}`}
                >
                  {group.label}
                </Link>
              ),
            )}
          </nav>
          <div className="flex-1 md:hidden" />
          <Link href="/data" className="inline-flex min-h-11 items-center px-2 text-muted md:hidden">
            소개
          </Link>
          <AccountButton />
        </div>
        {current && current.pages.length > 1 ? (
          <nav aria-label={`${current.label} 메뉴`} className="mx-auto flex max-w-5xl gap-1 overflow-x-auto px-4 pb-2 text-sm [scrollbar-width:none]">
            {current.pages.map((page) => (
              <Link
                key={page.href}
                href={page.href}
                aria-current={isOn(path, page.href) ? "page" : undefined}
                className={`inline-flex min-h-10 shrink-0 items-center gap-1.5 rounded-full border px-3 ${isOn(path, page.href) ? "border-accent bg-accent/10 font-semibold text-accent" : "border-line bg-white text-ink"}`}
              >
                <Icon name={page.icon} size={16} />
                {page.label}
                <SignedOutHint page={page} />
              </Link>
            ))}
          </nav>
        ) : null}
      </header>

      {/* Phones: the groups as bottom tabs (the 소개 page is the link in the bar above). */}
      <nav aria-label="하단 메뉴" className="fixed inset-x-0 bottom-0 z-30 grid grid-cols-4 border-t border-line bg-white pb-[env(safe-area-inset-bottom)] md:hidden">
        {tabs.map((tab) => {
          const active = tab.id === "home" ? path === "/" : current?.id === tab.id;
          return (
            <Link
              key={tab.id}
              href={tab.href}
              aria-current={active ? "page" : undefined}
              className={`flex h-16 flex-col items-center justify-center gap-1 text-xs ${active ? "font-bold text-accent" : "text-muted"}`}
            >
              <Icon name={tab.icon} size={22} />
              {tab.label}
            </Link>
          );
        })}
      </nav>
    </>
  );
}
