import type { Metadata, Viewport } from "next";

import AuthProvider from "@/components/AuthProvider";
import NavBar from "@/components/NavBar";

import "./globals.css";

export const metadata: Metadata = {
  title: "RagDog 반려견 AI 상담",
  description: "수의사 상담 자료와 공공 데이터를 근거로 답하는 반려견 건강 상담",
};

export const viewport: Viewport = { width: "device-width", initialScale: 1 };

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="ko">
      <body className="antialiased">
        {/* The first Tab stop: past the menu (two rows on a group's pages) straight to the page. */}
        <a
          href="#main"
          className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-2 focus:z-50 focus:rounded-lg focus:bg-white focus:px-4 focus:py-2 focus:font-semibold focus:text-accent focus:shadow"
        >
          본문으로 건너뛰기
        </a>
        <AuthProvider>
          <NavBar />
          {children}
          {/* Room for the phone's bottom tabs (components/NavBar.tsx). */}
          <div aria-hidden="true" className="h-20 md:hidden" />
        </AuthProvider>
      </body>
    </html>
  );
}
