import Chat from "@/components/Chat";

export default function Home() {
  return (
    <main className="mx-auto flex min-h-dvh w-full max-w-3xl flex-col px-4">
      <header className="py-6">
        <p className="text-sm font-semibold text-accent">반려동물 건강 정보</p>
        <h1 className="text-2xl font-bold text-ink">반려견 AI 상담</h1>
        <p className="mt-1 text-sm text-muted">수의사 상담 자료와 공공 데이터를 근거로 답합니다. 진료를 대신하지 않습니다.</p>
      </header>
      <Chat />
    </main>
  );
}
