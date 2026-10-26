"use client";

import { useState } from "react";

import type { Count } from "@/lib/stats";

// Categorical slots in fixed order (dataviz reference palette, light). Checked with validate_palette.js
// (2026-10-26): adjacent CVD ΔE 9.1, normal-vision 19.6. Three slots sit under 3:1 against white, so
// every slice is also named in the legend with its count and share, and the table repeats them.
const SLOTS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#6250d6"];
const SIZE = 180;
const RADIUS = 70;
const WIDTH = 28;

/** A part-to-whole of up to six classes as a donut (the dataviz rules: <= 6 segments, a 2px surface gap,
 * the legend names every slice in text ink, a hover/focus readout and a table view). */
export default function DonutChart({ title, unit, rows, note }: { title: string; unit: string; rows: Count[]; note?: string }) {
  const [active, setActive] = useState<number | null>(null);
  const shown = rows.slice(0, SLOTS.length);
  const total = shown.reduce((sum, row) => sum + row.count, 0) || 1;
  const share = (count: number) => `${Math.round((count / total) * 1000) / 10}%`;
  const circumference = 2 * Math.PI * RADIUS;
  let start = 0;
  return (
    <figure className="rounded-xl border border-line bg-white p-4">
      <figcaption className="mb-3">
        <span className="font-bold">{title}</span>
        {note ? <span className="ml-2 text-sm text-muted">{note}</span> : null}
      </figcaption>
      <div className="flex flex-col items-center gap-4 sm:flex-row sm:items-center sm:gap-8">
        <svg viewBox={`0 0 ${SIZE} ${SIZE}`} className="h-44 w-44 shrink-0" aria-hidden="true">
          <g transform={`rotate(-90 ${SIZE / 2} ${SIZE / 2})`}>
            {shown.map((row, index) => {
              const length = (row.count / total) * circumference;
              const slice = (
                <circle
                  key={row.label}
                  cx={SIZE / 2}
                  cy={SIZE / 2}
                  r={RADIUS}
                  fill="none"
                  stroke={SLOTS[index]}
                  strokeWidth={active === index ? WIDTH + 6 : WIDTH}
                  // a 2px gap of the surface between slices
                  strokeDasharray={`${Math.max(0, length - 2)} ${circumference}`}
                  strokeDashoffset={-start}
                  opacity={active !== null && active !== index ? 0.4 : 1}
                  onMouseEnter={() => setActive(index)}
                  onMouseLeave={() => setActive(null)}
                />
              );
              start += length;
              return slice;
            })}
          </g>
          <text x="50%" y="47%" textAnchor="middle" className="fill-muted text-[11px]">전체</text>
          <text x="50%" y="58%" textAnchor="middle" className="fill-ink text-[15px] font-bold">
            {total.toLocaleString()}{unit}
          </text>
        </svg>
        <ol className="w-full max-w-sm space-y-1.5" aria-label={title}>
          {shown.map((row, index) => (
            <li
              key={row.label}
              tabIndex={0}
              onMouseEnter={() => setActive(index)}
              onMouseLeave={() => setActive(null)}
              onFocus={() => setActive(index)}
              onBlur={() => setActive(null)}
              aria-label={`${row.label} ${row.count.toLocaleString()}${unit}`}
              className={`grid grid-cols-[0.75rem_1fr_auto_auto] items-center gap-2 rounded px-1 text-sm outline-none focus-visible:ring-2 focus-visible:ring-accent ${active === index ? "bg-page font-semibold" : ""}`}
            >
              <span className="h-3 w-3 rounded-sm" style={{ background: SLOTS[index] }} />
              <span className="truncate">{row.label}</span>
              <span className="tabular-nums">{row.count.toLocaleString()}</span>
              <span className="w-12 text-right tabular-nums text-muted">{share(row.count)}</span>
            </li>
          ))}
        </ol>
      </div>
      <p aria-live="polite" className="mt-3 min-h-5 text-sm text-muted">
        {active !== null
          ? `${shown[active].label}: ${shown[active].count.toLocaleString()}${unit} (전체의 ${share(shown[active].count)})`
          : "조각이나 항목에 마우스를 올리거나 Tab으로 옮기면 비율을 보여 줍니다."}
      </p>
      <details className="mt-1 text-sm">
        <summary className="cursor-pointer text-muted">표로 보기</summary>
        <table className="mt-2 w-full text-left">
          <thead className="text-muted">
            <tr>
              <th className="py-1">항목</th>
              <th className="py-1 text-right">{unit}</th>
              <th className="py-1 text-right">비율</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((row) => (
              <tr key={row.label} className="border-t border-line">
                <td className="py-1">{row.label}</td>
                <td className="py-1 text-right tabular-nums">{row.count.toLocaleString()}</td>
                <td className="py-1 text-right tabular-nums">{share(row.count)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </figure>
  );
}
