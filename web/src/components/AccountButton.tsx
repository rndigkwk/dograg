"use client";

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
      <span className="ml-auto flex shrink-0 items-center gap-2">
        {error ? <span role="alert" className="text-xs text-danger">로그인을 시작하지 못했습니다</span> : null}
        <button
          type="button"
          disabled={busy}
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
          Google로 로그인
        </button>
      </span>
    );
  }

  const email = session.user.email ?? "로그인됨";
  return (
    <span className="ml-auto flex shrink-0 items-center gap-2">
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
