// How the evidence under an answer is labelled, as on the Streamlit chat page
// (app_pages/rag.py format_evidence_row, render_report_evidence).

export type Row = Record<string, unknown>;

const text = (value: unknown): string => (value === undefined || value === null ? "" : String(value));

/** A health answer's evidence: a vet consultation, labelled by life stage, department, disease.
 * "사례 n" is the number the answer cites ([사례 n], src/citations.py). */
export function consultation(row: Row, index: number): { title: string; answer: string } {
  const pick = (...keys: string[]) => keys.map((key) => text(row[key])).find(Boolean) || "-";
  return {
    title: `사례 ${index + 1} · ${pick("meta.lifeCycle", "lifeCycle")} / ${pick("meta.department", "department")} / ${pick("meta.disease", "disease")}`,
    answer: text(row["qa.output"]) || text(row.answer),
  };
}

/** A public care guide (동물사랑배움터, src/tools/care_guides.py) among a health answer's evidence. */
export const isGuide = (row: Row): boolean => row.kind === "care_guide";

/** A care guide's evidence: the guide and page, the piece the answer used, and the guide's own page. */
export function guide(row: Row, index: number): { title: string; organization: string; excerpt: string; url: string } {
  const page = row.page ? ` · ${text(row.page)}쪽` : "";
  const url = text(row.url);
  return {
    title: `지침 ${index + 1} · ${text(row.title) || "돌봄 지침"}${page}`,
    organization: text(row.organization),
    excerpt: text(row.piece),
    url: url.startsWith("https://") ? url : "",
  };
}

export const EXCERPT_PREVIEW_CHARS = 150; // about 2-3 lines; the rest is behind 자세히 보기

/** A report answer's evidence: report title, page, and the first lines of the excerpt. */
export const SCANNED_NOTE = "보고서 그림 속 숫자를 스캔(OCR)으로 읽은 글이라 글자가 틀릴 수 있어요. 원문 페이지로 확인하세요.";

/** A report answer's evidence; `scanned` when the text was read from the page image (OCR). */
export function reportPage(row: Row, index: number): { title: string; preview: string; excerpt: string; scanned: boolean } {
  const page = row.page ? `페이지 ${text(row.page)}` : "페이지 확인 불가";
  const excerpt = text(row.excerpt);
  const flat = excerpt.split(/\s+/).filter(Boolean).join(" ");
  const preview = flat.length <= EXCERPT_PREVIEW_CHARS ? flat : `${flat.slice(0, EXCERPT_PREVIEW_CHARS).trimEnd()}…`;
  return { title: `근거 ${index + 1} · ${text(row.title) || "2025 한국 반려동물 보고서"} · ${page}`, preview, excerpt, scanned: row.scanned === true };
}
