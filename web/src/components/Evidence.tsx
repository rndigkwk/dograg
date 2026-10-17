import { consultation, reportPage, type Row, SCANNED_NOTE } from "@/lib/evidence";

import Markdown from "./Markdown";

/** The material an answer stands on: vet consultations for health, report pages for analysis. */
export default function Evidence({ route, rows }: { route?: string; rows: Row[] }) {
  if (!rows.length) return null;
  if (route === "analysis") {
    return (
      <section className="mt-4" aria-label="보고서 근거">
        <h3 className="mb-2 font-bold">보고서 근거</h3>
        <ul className="space-y-2">
          {rows.map((row, index) => {
            const page = reportPage(row, index);
            return (
              <li key={index} className="rounded-lg border border-line p-3">
                <p className="font-semibold">
                  {page.title}
                  {page.scanned ? <span className="ml-2 rounded bg-warn/15 px-1.5 py-0.5 text-xs font-normal text-warn-strong">스캔 글(OCR)</span> : null}
                </p>
                {page.scanned ? <p className="mt-0.5 text-xs text-muted">{SCANNED_NOTE}</p> : null}
                <details className="mt-1 text-sm">
                  <summary className="cursor-pointer text-muted">{page.preview || "내용 없음"}</summary>
                  <p className="mt-2 whitespace-pre-wrap">{page.excerpt}</p>
                </details>
              </li>
            );
          })}
        </ul>
      </section>
    );
  }
  return (
    <section className="mt-4" aria-label="검색 근거">
      <h3 className="mb-2 font-bold">검색 근거</h3>
      <div className="space-y-1">
        {rows.map((row, index) => {
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
