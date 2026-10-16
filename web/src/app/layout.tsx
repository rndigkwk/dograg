import type { Metadata, Viewport } from "next";

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
        <NavBar />
        {children}
      </body>
    </html>
  );
}
