import { citeKey, consultation, guide, isGuide, reportPage, type Row, SCANNED_NOTE } from "@/lib/evidence";

import Markdown from "./Markdown";

/** The material an answer stands on: vet consultations (and care guides) for health, report pages for analysis.
 * `folded` (a finished health answer, 2026-11-06 guardian-view mockup): the cards sit in one closed fold
 * under the answer, so the answer and what to do come first; a citation in the answer still opens its card. */
export default function Evidence({ route, rows, folded = false }: { route?: string; rows: Row[]; folded?: boolean }) {
  if (!rows.length) return null;
  if (route === "analysis") {
    // The pages the answer cites come first (src/report_evidence.py evidence_for_display); the rest fold.
    const cited = rows.filter((row) => row.cited === true);
    const page = (row: Row, index: number) => {
      const item = reportPage(row, index);
      return (
        <li key={index} className="rounded-lg border border-line p-3">
          <p className="font-semibold">
            {item.title}
            {item.scanned ? <span className="ml-2 rounded bg-warn/15 px-1.5 py-0.5 text-xs font-normal text-warn-strong">스캔 글(OCR)</span> : null}
          </p>
          {item.scanned ? <p className="mt-0.5 text-xs text-muted">{SCANNED_NOTE}</p> : null}
          <details className="mt-1 text-sm">
            <summary className="cursor-pointer text-muted">{item.preview || "내용 없음"}</summary>
            <p className="mt-2 whitespace-pre-wrap">{item.excerpt}</p>
          </details>
        </li>
      );
    };
    const shown = cited.length ? cited : rows;
    const rest = rows.slice(shown.length);
    return (
      <section className="mt-4" aria-label="보고서 근거">
        <h3 className="mb-2 font-bold">{cited.length ? "답에 인용된 보고서 근거" : "보고서 근거"}</h3>
        <ul className="space-y-2">{shown.map(page)}</ul>
        {rest.length ? (
          <details className="mt-2 text-sm">
            <summary className="cursor-pointer text-muted">함께 찾은 다른 근거 {rest.length}개</summary>
            <ul className="mt-2 space-y-2">{rest.map((row, index) => page(row, shown.length + index))}</ul>
          </details>
        ) : null}
      </section>
    );
  }
  const cases = rows.filter((row) => !isGuide(row));
  const guides = rows.filter(isGuide);
  const cards = (
      <div className="space-y-1">
        {guides.map((row, index) => {
          const item = guide(row, index);
          return (
            <details key={`guide-${index}`} data-cite={citeKey("guide", index + 1)} className="rounded-lg border border-line px-3 py-2 text-sm">
              <summary className="cursor-pointer">{item.title}</summary>
              <div className="mt-2 space-y-1">
                <p className="whitespace-pre-wrap">{item.excerpt}</p>
                <p className="text-xs text-muted">
                  출처: {item.organization}
                  {item.url ? (
                    <>
                      {" · "}
                      <a href={item.url} target="_blank" rel="noopener noreferrer" className="underline">
                        원문 보기
                      </a>
                    </>
                  ) : null}
                </p>
              </div>
            </details>
          );
        })}
        {cases.map((row, index) => {
          const item = consultation(row, index);
          return (
            <details key={index} data-cite={citeKey("case", index + 1)} className="rounded-lg border border-line px-3 py-2 text-sm">
              <summary className="cursor-pointer">{item.title}</summary>
              <div className="mt-2 space-y-2">
                {item.question ? (
                  <div>
                    <p className="font-semibold">다른 보호자의 질문</p>
                    <p className="whitespace-pre-wrap">{item.question}</p>
                  </div>
                ) : null}
                <div>
                  <p className="font-semibold">수의사 답변</p>
                  <Markdown text={item.answer} />
                </div>
                {/* The source's labels, which often do not match the text: kept, but last and quiet. */}
                <p className="text-xs text-muted">자료 분류: {item.labels} (상담 내용과 다를 수 있어요)</p>
              </div>
            </details>
          );
        })}
      </div>
  );
  const counted = [cases.length ? `수의사 상담 ${cases.length}건` : "", guides.length ? `돌봄 지침 ${guides.length}건` : ""].filter(Boolean).join(" · ");
  if (folded)
    return (
      <details data-evidence className="mt-4 border-t border-line pt-3">
        <summary className="cursor-pointer text-sm font-semibold text-accent">근거 자료 보기 ({counted})</summary>
        <section className="mt-2" aria-label="검색 근거">
          {cards}
        </section>
      </details>
    );
  return (
    <section className="mt-4" aria-label="검색 근거">
      <h3 className="mb-2 font-bold">검색 근거</h3>
      {cards}
    </section>
  );
}
