// The five PDF reports the report page asks (src/tools/report.py; data/source/*.pdf). Publisher and
// date as printed on each report's cover or imprint page.

export type Report = {
  id: string;
  title: string;
  publisher: string;
  published: string;
  pages: number;
  covers: string;
  // How a question names this report, so the search (BM25 + embeddings) leans to it.
  name: string;
  questions: string[];
};

export const REPORTS: Report[] = [
  {
    id: "kb2025",
    title: "2025 한국 반려동물 보고서",
    publisher: "KB경영연구소",
    published: "2025.6",
    pages: 112,
    covers: "반려가구 수, 양육비·치료비, 펫보험, 혼자 있는 시간, 비만 관리",
    name: "KB 2025 한국 반려동물 보고서",
    questions: ["국내 반려가구 수와 반려인 수는 각각 얼마인가요?", "펫보험 가입률은 2023년과 비교해 어떻게 달라졌나요?"],
  },
  {
    id: "welfare",
    title: "반려동물 복지실태와 개선과제",
    publisher: "한국농촌경제연구원",
    published: "2024.10",
    pages: 273,
    covers: "동물복지 다섯 영역, 생산업 기준, 소유자의 돌봄 실태",
    name: "반려동물 복지실태와 개선과제 보고서",
    questions: ["동물복지의 다섯 영역은 무엇인가요?", "혼자 있는 동물을 홈캠이나 CCTV로 확인하는 비율은?"],
  },
  {
    id: "industry",
    title: "반려동물 산업 조사체계 진단 및 실태조사",
    publisher: "한국농촌경제연구원",
    published: "2024.4",
    pages: 284,
    covers: "양육자 조사 설계, 미용·위탁관리 등 업종별 업체 수",
    name: "반려동물 산업 조사체계 진단 및 실태조사",
    questions: ["2022년 동물미용업과 동물위탁관리업 업체 수는 각각 얼마인가요?"],
  },
  {
    id: "medical",
    title: "반려동물 의료·보험서비스 시장 진단 및 개선방안 연구",
    publisher: "한국소비자원",
    published: "2025",
    pages: 184,
    covers: "동물병원 가격 인식, 소비자시장평가 경고 지표, 펫보험",
    name: "반려동물 의료·보험서비스 시장 연구",
    questions: ["동물병원 소비자가 실제 낸 평균 가격과 기대한 평균 가격은 얼마인가요?"],
  },
  {
    id: "funeral",
    title: "반려동물 장묘서비스 이용 실태조사",
    publisher: "한국소비자원",
    published: "2022.12",
    pages: 69,
    covers: "장묘 소비자 불만, 업체 온라인 예약, 종합 정보시스템 제안",
    name: "반려동물 장묘서비스 이용 실태조사",
    questions: ["가장 많은 소비자 불만 유형과 건수는?", "온라인 예약이 가능한 업체 수와 비율은?"],
  },
];

// Questions that draw on several reports at once (each one is in tests/data/report_reference_answers.json).
export const CROSS_QUESTIONS = [
  "KB 2025 보고서와 복지실태 보고서에서 반려동물이 혼자 있는 하루 평균 시간을 비교하고, 홈캠·CCTV로 확인하는 비율과 함께 정리해 줘.",
  "동물병원 소비자가 실제 낸 평균 가격과 기대한 가격, 소비자시장평가에서 경고로 지적된 지표, KB 2025의 펫보험 가입률 변화를 묶어서 의료비 부담을 정리해 줘.",
  "장묘서비스 실태조사에서 가장 많은 소비자 불만 유형, 온라인 예약이 되는 업체 비율, 개선안으로 제안된 종합 정보시스템을 정리해 줘.",
];

/** The question as sent: with a report chosen, it names that report first (unless it already does). */
export function scoped(question: string, report: Report | null): string {
  const text = question.trim();
  if (!report || text.includes(report.name) || text.includes(report.title)) return text;
  return `${report.name}에서 ${text}`;
}
