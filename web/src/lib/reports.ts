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
    questions: [
      "2024년 말 기준 반려인 수와 총인구 대비 비중, 전년 대비 증가 폭은?",
      "월평균 양육비 중 식비 비중은 얼마이고 이전 조사보다 얼마나 늘었나요?",
      "집에 혼자 남겨지는 반려동물 비율과 하루 평균 시간은?",
      "펫보험 가입률은 2023년과 비교해 어떻게 달라졌나요?",
      "반려동물보험 시장 활성화를 위한 최우선 과제로 꼽힌 것과 그 비율은?",
    ],
  },
  {
    id: "welfare",
    title: "반려동물 복지실태와 개선과제",
    publisher: "한국농촌경제연구원",
    published: "2024.10",
    pages: 273,
    covers: "동물복지 다섯 영역, 생산업 기준, 소유자의 돌봄 실태",
    name: "반려동물 복지실태와 개선과제 보고서",
    questions: [
      "동물복지의 다섯 영역은 무엇인가요?",
      "혼자 있는 동물을 홈캠이나 CCTV로 확인하는 비율은?",
      "고양이가 집에 혼자 남는 시간은 하루 평균 몇 시간인가요?",
      "지금 키우는 반려동물이 죽으면 땅에 묻겠다는 비율은?",
      "동물생산업 사육관리 인력 기준은 종전 몇 마리당 1명에서 몇 마리당 1명으로 강화됐나요?",
    ],
  },
  {
    id: "industry",
    title: "반려동물 산업 조사체계 진단 및 실태조사",
    publisher: "한국농촌경제연구원",
    published: "2024.4",
    pages: 284,
    covers: "양육자 조사 설계, 미용·위탁관리 등 업종별 업체 수",
    name: "반려동물 산업 조사체계 진단 및 실태조사",
    questions: [
      "2022년 동물미용업과 동물위탁관리업 업체 수는 각각 얼마인가요?",
      "양육자가 앞으로의 반려동물 장례 방법으로 가장 많이 꼽은 것은?",
      "고양이 보험에 든 비율은 몇 %인가요?",
      "2024년 양육자·미양육자 온라인 조사 기간과 전체 표본 수는?",
      "양육자 조사에서 주양육자·공동양육자·보조양육자 중 누가 응답 대상인가요?",
    ],
  },
  {
    id: "medical",
    title: "반려동물 의료·보험서비스 시장 진단 및 개선방안 연구",
    publisher: "한국소비자원",
    published: "2025",
    pages: 184,
    covers: "동물병원 가격 인식, 소비자시장평가 경고 지표, 펫보험",
    name: "반려동물 의료·보험서비스 시장 연구",
    questions: [
      "동물병원 소비자가 실제 낸 평균 가격과 기대한 평균 가격은 얼마인가요?",
      "양육자의 몇 %가 동물병원 진료비에 부담을 느낀다고 했나요?",
      "2024 소비자시장평가지표에서 경고 영역으로 지적된 동물병원 서비스의 두 지표는?",
      "전문가들이 동물병원 진료비가 비싸다고 보는 주된 이유는 무엇인가요?",
      "델파이 조사 참여 인원과 2025년 조사 기간은?",
    ],
  },
  {
    id: "funeral",
    title: "반려동물 장묘서비스 이용 실태조사",
    publisher: "한국소비자원",
    published: "2022.12",
    pages: 69,
    covers: "장묘 소비자 불만, 업체 온라인 예약, 종합 정보시스템 제안",
    name: "반려동물 장묘서비스 이용 실태조사",
    questions: [
      "2019~2022년 8월 상담 중 가장 많은 소비자 불만 유형과 건수는?",
      "조사한 업체 중 홈페이지에서 온라인 예약이 가능한 업체 수와 비율은?",
      "등록된 동물장묘업체 수는 2013년과 2022년에 각각 몇 곳인가요?",
      "반려동물이 죽은 뒤 장묘시설을 이용하게 된 경로 중 가장 많은 것은?",
      "e하늘을 본떠 제안한 종합 정보시스템에 담을 정보와 예약 기능은 무엇인가요?",
    ],
  },
];

// Questions that draw on several reports at once (the first card, "5종 통합"). Each report's questions and
// these come from tests/data/report_reference_answers.json, except two checked by search only (2026-10-26):
// the medical report's "비싸다고 보는 이유" (p.100) and the funeral report's "이용 경로" (p.26).
export const CROSS_QUESTIONS = [
  "펫보험(반려동물보험) 가입률은 보고서마다 몇 %로 나오나요?",
  "세상을 떠난 반려동물을 직접 땅에 묻은 비율은 보고서마다 어떻게 나오나요?",
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
