"use client";

import Link from "next/link";
import { useState } from "react";

import { signInWithGoogle, signOut } from "@/lib/supabase";

import { useAuth } from "./AuthProvider";

/** Sign in with Google, or the signed-in account with sign-out (the menu's right end). */
export default function AccountButton() {
  const { session, ready } = useAuth();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(false);
  if (!ready) return null;

  if (!session) {
    return (
      <span className="flex shrink-0 items-center gap-2">
        {error ? <span role="alert" className="text-xs text-danger">로그인을 시작하지 못했습니다</span> : null}
        <button
          type="button"
          disabled={busy}
          aria-label="Google로 로그인"
          onClick={async () => {
            setBusy(true);
            setError(false);
            try {
              await signInWithGoogle(); // leaves the page for Google
            } catch {
              setError(true);
              setBusy(false);
            }
          }}
          className="rounded-lg border border-line bg-white px-3 py-1.5 disabled:opacity-40"
        >
          <span className="sm:hidden">로그인</span>
          <span className="hidden sm:inline">Google로 로그인</span>
        </button>
      </span>
    );
  }

  const email = session.user.email ?? "로그인됨";
  return (
    <span className="flex shrink-0 items-center gap-2">
      <Link href="/memory" className="rounded-lg px-2 py-1.5 text-ink hover:bg-line/50" title="지난 상담 기억">
        🗂<span className="hidden sm:inline"> 기억</span>
      </Link>
      <span className="hidden max-w-48 truncate text-muted sm:inline" title={email}>
        {email}
      </span>
      <button
        type="button"
        disabled={busy}
        onClick={async () => {
          setBusy(true);
          await signOut();
          setBusy(false);
        }}
        className="rounded-lg border border-line bg-white px-3 py-1.5 disabled:opacity-40"
      >
        로그아웃
      </button>
    </span>
  );
}
