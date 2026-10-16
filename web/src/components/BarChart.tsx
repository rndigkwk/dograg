"use client";

import { useState } from "react";

import type { Count } from "@/lib/stats";

/** A ranked count as horizontal bars: one series in the accent color, the value at each tip in text ink,
 * a hover/focus readout, and the same numbers as a table (the dataviz rules: one hue for one series,
 * text never in the data color, a table view). */
export default function BarChart({ title, unit, rows, note }: { title: string; unit: string; rows: Count[]; note?: string }) {
  const [active, setActive] = useState<number | null>(null);
  const max = Math.max(1, ...rows.map((row) => row.count));
  const total = rows.reduce((sum, row) => sum + row.count, 0);
  return (
    <figure className="rounded-xl border border-line bg-white p-4">
      <figcaption className="mb-3">
        <span className="font-bold">{title}</span>
        {note ? <span className="ml-2 text-sm text-muted">{note}</span> : null}
      </figcaption>
      <ol className="space-y-1.5" aria-label={title}>
        {rows.map((row, index) => (
          <li
            key={row.label}
            tabIndex={0}
            onMouseEnter={() => setActive(index)}
            onMouseLeave={() => setActive(null)}
            onFocus={() => setActive(index)}
            onBlur={() => setActive(null)}
            aria-label={`${row.label} ${row.count.toLocaleString()}${unit}`}
            className="grid grid-cols-[minmax(5.5rem,9rem)_1fr] items-center gap-3 rounded outline-none focus-visible:ring-2 focus-visible:ring-accent"
          >
            <span className={`truncate text-sm ${active === index ? "font-semibold" : ""}`} title={row.label}>
              {row.label}
            </span>
            <span className="flex items-center gap-2">
              {/* <= 24px thick, square at the baseline, 4px rounded at the data end. */}
              <span
                className={`h-5 rounded-r bg-accent transition-opacity ${active !== null && active !== index ? "opacity-40" : ""}`}
                style={{ width: `${Math.max(1, (row.count / max) * 100) * 0.82}%` }}
              />
              <span className="shrink-0 text-sm tabular-nums text-ink">{row.count.toLocaleString()}</span>
            </span>
          </li>
        ))}
      </ol>
      <p aria-live="polite" className="mt-3 min-h-5 text-sm text-muted">
        {active !== null
          ? `${rows[active].label}: ${rows[active].count.toLocaleString()}${unit} (전체의 ${Math.round((rows[active].count / total) * 1000) / 10}%)`
          : "막대에 마우스를 올리거나 Tab으로 옮기면 비율을 보여 줍니다."}
      </p>
      <details className="mt-1 text-sm">
        <summary className="cursor-pointer text-muted">표로 보기</summary>
        <table className="mt-2 w-full text-left">
          <thead className="text-muted">
            <tr>
              <th className="py-1">항목</th>
              <th className="py-1 text-right">{unit}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.label} className="border-t border-line">
                <td className="py-1">{row.label}</td>
                <td className="py-1 text-right tabular-nums">{row.count.toLocaleString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </figure>
  );
}
