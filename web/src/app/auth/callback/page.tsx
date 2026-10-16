import type { Metadata } from "next";
import { Suspense } from "react";

import AuthCallback from "@/components/AuthCallback";

export const metadata: Metadata = { title: "로그인 · 라그도그", robots: { index: false } };

export default function AuthCallbackPage() {
  return (
    <main className="mx-auto w-full max-w-md px-4 py-16 text-center">
      <Suspense>
        <AuthCallback />
      </Suspense>
    </main>
  );
}
