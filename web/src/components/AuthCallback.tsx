"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";

import { supabase, takeReturnPath } from "@/lib/supabase";

/** Back from Google: the Supabase client trades ?code= for a session (PKCE), then the page the
 * guardian was on opens again. An error or a missing session says so instead. */
export default function AuthCallback() {
  const router = useRouter();
  const params = useSearchParams();
  const [failed, setFailed] = useState(params.has("error"));

  useEffect(() => {
    if (failed) return;
    const client = supabase();
    let done = false;
    const finish = () => {
      if (done) return;
      done = true;
      router.replace(takeReturnPath());
    };
    const { data } = client.auth.onAuthStateChange((_event, session) => {
      if (session) finish();
    });
    client.auth.getSession().then(({ data: current }) => {
      if (current.session) finish();
    });
    const timer = window.setTimeout(() => {
      if (!done) setFailed(true);
    }, 15000);
    return () => {
      data.subscription.unsubscribe();
      window.clearTimeout(timer);
    };
  }, [failed, router]);

  if (failed) {
    return (
      <div className="space-y-3">
        <p role="alert" className="text-danger">로그인하지 못했습니다. 다시 시도해 주세요.</p>
        <Link href="/" className="text-accent underline">홈으로</Link>
      </div>
    );
  }
  return <p role="status" className="text-muted">로그인하는 중입니다…</p>;
}
