import { consultation, guide, isGuide, reportPage, type Row, SCANNED_NOTE } from "@/lib/evidence";

import Markdown from "./Markdown";

/** The material an answer stands on: vet consultations (and care guides) for health, report pages for analysis. */
export default function Evidence({ route, rows }: { route?: string; rows: Row[] }) {
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
  return (
    <section className="mt-4" aria-label="검색 근거">
      <h3 className="mb-2 font-bold">검색 근거</h3>
      <div className="space-y-1">
        {guides.map((row, index) => {
          const item = guide(row, index);
          return (
            <details key={`guide-${index}`} className="rounded-lg border border-line px-3 py-2 text-sm">
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
            <details key={index} className="rounded-lg border border-line px-3 py-2 text-sm">
              <summary className="cursor-pointer">{item.title}</summary>
              <div className="mt-2">
                <p className="font-semibold">답변</p>
                <Markdown text={item.answer} />
              </div>
            </details>
          );
        })}
      </div>
    </section>
  );
}
