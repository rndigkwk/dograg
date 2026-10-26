/** Above any clinic-fee figure (2026-10-26): they are the Ministry of Agriculture's 2025 survey
 * statistics by area, not a clinic's price list. Said first, not only in the notes under the figures. */
export default function FeeSourceNotice({ compact = false }: { compact?: boolean }) {
  return (
    <p role="note" className={`rounded-lg border border-warn/40 bg-warn/10 ${compact ? "px-3 py-2" : "p-3"} text-sm`}>
      <span className="font-semibold text-warn-strong">⚠️ 실제 가격이 아닙니다.</span>{" "}
      농림축산식품부 「2025 동물병원 진료비 현황 조사」의 <strong>지역 통계(중간값·평균)</strong>입니다. 같은 항목도
      병원·검사 범위·반려견 상태에 따라 달라지니 방문 전에 병원에 전화로 확인하세요.
    </p>
  );
}
