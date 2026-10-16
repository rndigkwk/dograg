import { type MemorySuggestion, profileSummary } from "@/lib/profile";

/** After a health answer: facts about the dog to remember. Nothing is saved without a click
 * (app_pages/rag.py render_profile_suggestion). */
export default function MemoryCard({ suggestion, onSave, onDismiss }: { suggestion: MemorySuggestion; onSave: () => void; onDismiss: () => void }) {
  const { update } = suggestion;
  return (
    <div role="region" aria-label="기억 제안" className="rounded-xl border border-accent/40 bg-white p-4 text-sm">
      <p>
        <strong>{update ? "새로 알게 된 정보를 기억할까요?" : "대화에서 반려견 정보를 찾았어요."}</strong>{" "}
        {update ? suggestion.summary : profileSummary(suggestion.profile)}
      </p>
      <p className="mt-1 text-muted">
        {update
          ? "기억하면 이 브라우저의 '우리 아이 정보'에 더해지고, 다음 상담부터 답변에 반영됩니다."
          : "저장하면 이 브라우저에만 남고, 다음 상담부터 나이에 맞는 자료를 먼저 찾습니다."}
      </p>
      <div className="mt-3 flex gap-2">
        <button type="button" onClick={onSave} className="flex-1 rounded-lg bg-accent px-3 py-2 font-semibold text-white">
          {update ? "기억하기" : "우리 아이 정보에 저장"}
        </button>
        <button type="button" onClick={onDismiss} className="flex-1 rounded-lg border border-line px-3 py-2">
          {update ? "기억하지 않기" : "저장하지 않기"}
        </button>
      </div>
    </div>
  );
}
