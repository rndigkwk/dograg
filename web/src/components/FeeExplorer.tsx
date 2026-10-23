"use client";

import { useEffect, useMemo, useState } from "react";

import {
  byMedian,
  type FeeItem,
  feeItems,
  type FeeValues,
  gapLabel,
  groupByCategory,
  type ItemFees,
  itemFees,
  shortSido,
  versusNational,
  won,
} from "@/lib/fees";
import { failureMessage } from "@/lib/failure";

import Waiting, { LoadError } from "./Waiting";

const DEFAULT_ITEM = "초진 진찰료 (체중 5kg)";
const ALL = "";

function Stat({ label, value, strong }: { label: string; value: number; strong?: boolean }) {
  return (
    <div className="rounded-lg border border-line bg-white px-3 py-2">
      <div className="text-xs text-muted">{label}</div>
      <div className={`tabular-nums ${strong ? "text-2xl font-bold" : "text-lg font-semibold"}`}>{won(value)}</div>
    </div>
  );
}

/** The chosen region's numbers: the median large (what most clinics charge), then mean, min, max. */
function Summary({ title, values, national }: { title: string; values: FeeValues; national: FeeValues | null }) {
  return (
    <section aria-label={`${title} 진료비`} className="rounded-xl border border-line bg-white p-4">
      <h2 className="mb-3 font-bold">{title}</h2>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <Stat label="중간값" value={values.median} strong />
        <Stat label="평균" value={values.mean} />
        <Stat label="최저" value={values.min} />
        <Stat label="최고" value={values.max} />
      </div>
      {national ? <p className="mt-2 text-sm text-muted">중간값 기준 {versusNational(values.median, national.median)}</p> : null}
    </section>
  );
}

/** Provinces' medians as one-hue bars, ranked, with the national median as a dashed rule; the chosen
 * province stays solid and the rest fade. Hover or focus reads a row out; a click chooses it. */
function SidoChart({ fees, chosen, onChoose }: { fees: ItemFees; chosen: string; onChoose: (sido: string) => void }) {
  const [active, setActive] = useState<string | null>(null);
  const rows = useMemo(() => byMedian(fees.sido), [fees.sido]);
  const max = Math.max(1, fees.national.median, ...rows.map((row) => row.median));
  const scale = (value: number) => (value / max) * 100;
  const shown = rows.find((row) => row.sido === active);
  return (
    <figure className="rounded-xl border border-line bg-white p-4">
      <figcaption className="mb-3">
        <span className="font-bold">시·도별 중간값</span>
        <span className="ml-2 text-sm text-muted">점선과 회색 숫자는 전국 중간값 {won(fees.national.median)} 대비 · 막대를 누르면 그 시·도를 고릅니다</span>
      </figcaption>
      <ol className="space-y-1.5" aria-label="시·도별 중간값">
        {rows.map((row) => {
          const faded = (chosen && chosen !== row.sido) || (active !== null && active !== row.sido);
          return (
            <li key={row.sido}>
              <button
                type="button"
                onMouseEnter={() => setActive(row.sido)}
                onMouseLeave={() => setActive(null)}
                onFocus={() => setActive(row.sido)}
                onBlur={() => setActive(null)}
                onClick={() => onChoose(chosen === row.sido ? ALL : row.sido)}
                aria-pressed={chosen === row.sido}
                aria-label={`${row.sido} 중간값 ${won(row.median)}`}
                className="grid w-full grid-cols-[2.5rem_1fr_auto] items-center gap-2 rounded text-left outline-none focus-visible:ring-2 focus-visible:ring-accent"
              >
                <span className={`text-sm ${chosen === row.sido ? "font-bold text-accent" : ""}`}>{shortSido(row.sido)}</span>
                {/* The track: bars and the national rule share one scale, so nothing spills past it. */}
                <span className="relative h-6 min-w-0">
                  <span
                    className={`absolute inset-y-0.5 left-0 rounded-r bg-accent transition-opacity ${faded ? "opacity-35" : ""}`}
                    style={{ width: `${Math.max(0.5, scale(row.median))}%` }}
                  />
                  <span
                    aria-hidden
                    className="pointer-events-none absolute inset-y-0 border-l-2 border-dashed border-ink/50"
                    style={{ left: `${scale(fees.national.median)}%` }}
                  />
                </span>
                <span className="w-[7.5rem] text-right text-sm tabular-nums text-ink">
                  {row.median.toLocaleString("ko-KR")} <span className="text-xs text-muted">{gapLabel(row.median, fees.national.median)}</span>
                </span>
              </button>
            </li>
          );
        })}
      </ol>
      {fees.no_data.length ? (
        <p className="mt-2 text-xs text-muted">자료 없음: {fees.no_data.map(shortSido).join(", ")} (해당 진료가 없거나 병원이 1곳 이하인 지역은 공개되지 않습니다)</p>
      ) : null}
      <p aria-live="polite" className="mt-3 min-h-5 text-sm text-muted">
        {shown
          ? `${shown.sido}: 중간 ${won(shown.median)} · 평균 ${won(shown.mean)} · ${won(shown.min)} ~ ${won(shown.max)} (${versusNational(shown.median, fees.national.median)})`
          : "막대에 마우스를 올리거나 Tab으로 옮기면 평균과 범위를 보여 줍니다."}
      </p>
    </figure>
  );
}

function SigunguTable({ fees, sido, chosen, onChoose }: { fees: ItemFees; sido: string; chosen: string; onChoose: (gu: string) => void }) {
  const rows = byMedian(fees.sigungu.filter((row) => row.sido === sido));
  if (!rows.length) return <p className="text-sm text-muted">{sido}의 시·군·구 자료가 없습니다(병원이 1곳 이하인 지역은 공개되지 않습니다).</p>;
  return (
    <section className="rounded-xl border border-line bg-white p-4">
      <h2 className="mb-2 font-bold">{sido} 시·군·구 ({rows.length}곳, 중간값 높은 순)</h2>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[28rem] text-left text-sm">
          <thead className="text-muted">
            <tr>
              <th className="py-1 pr-3">시·군·구</th>
              <th className="py-1 pr-3 text-right">중간값</th>
              <th className="py-1 pr-3 text-right">평균</th>
              <th className="py-1 text-right">최저 ~ 최고</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr
                key={row.sigungu}
                onClick={() => onChoose(chosen === row.sigungu ? ALL : row.sigungu)}
                className={`cursor-pointer border-t border-line hover:bg-accent/5 ${chosen === row.sigungu ? "bg-accent/10 font-semibold" : ""}`}
              >
                <td className="py-1 pr-3">{row.sigungu}</td>
                <td className="py-1 pr-3 text-right tabular-nums">{won(row.median)}</td>
                <td className="py-1 pr-3 text-right tabular-nums">{won(row.mean)}</td>
                <td className="py-1 text-right tabular-nums">
                  {won(row.min)} ~ {won(row.max)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

/** The fee page: pick a surveyed item and a region; see that region's numbers, every province against
 * the national median, and the districts of the chosen province (animalclinicfee.or.kr's view). */
export default function FeeExplorer() {
  const [items, setItems] = useState<FeeItem[] | null>(null);
  const [itemLabel, setItemLabel] = useState(DEFAULT_ITEM);
  const [fees, setFees] = useState<ItemFees | null>(null);
  const [sido, setSido] = useState(ALL);
  const [gu, setGu] = useState(ALL);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    feeItems().then((body) => setItems(body.items), (e: Error) => setError(failureMessage(e, e.message)));
  }, [attempt]);

  const item = items?.find((candidate) => candidate.label === itemLabel) ?? items?.[0];
  useEffect(() => {
    if (!item) return;
    let current = true;
    itemFees(item).then(
      (body) => current && setFees(body),
      (e: Error) => current && setError(failureMessage(e, e.message)),
    );
    return () => {
      current = false;
    };
  }, [item, attempt]);

  if (error)
    return (
      <LoadError
        message={error}
        onRetry={() => {
          setError(null);
          setAttempt((n) => n + 1);
        }}
      />
    );
  if (!items || !fees) return <Waiting text="진료비 자료를 불러오는 중입니다…" />;

  const sidoRow = fees.sido.find((row) => row.sido === sido);
  const guRow = fees.sigungu.find((row) => row.sido === sido && row.sigungu === gu);
  const [title, values] = guRow ? [`${sido} ${gu}`, guRow] : sidoRow ? [sido, sidoRow] : ["전국", fees.national];
  const districts = fees.sigungu.filter((row) => row.sido === sido).map((row) => row.sigungu).sort((a, b) => a.localeCompare(b, "ko"));
  const chooseSido = (next: string) => {
    setSido(next);
    setGu(ALL);
  };

  return (
    <div className="space-y-4">
      <div className="grid gap-3 rounded-xl border border-line bg-white p-4 sm:grid-cols-3">
        <label className="text-sm">
          <span className="mb-1 block font-semibold">진료 항목</span>
          <select value={item?.label} onChange={(e) => setItemLabel(e.target.value)} className="w-full rounded-lg border border-line bg-white px-2 py-2">
            {groupByCategory(items).map(([category, group]) => (
              <optgroup key={category} label={category}>
                {group.map((option) => (
                  <option key={option.label}>{option.label}</option>
                ))}
              </optgroup>
            ))}
          </select>
        </label>
        <label className="text-sm">
          <span className="mb-1 block font-semibold">시·도</span>
          <select value={sido} onChange={(e) => chooseSido(e.target.value)} className="w-full rounded-lg border border-line bg-white px-2 py-2">
            <option value={ALL}>전국</option>
            {fees.sido.map((row) => row.sido).sort((a, b) => a.localeCompare(b, "ko")).map((name) => (
              <option key={name}>{name}</option>
            ))}
          </select>
        </label>
        <label className="text-sm">
          <span className="mb-1 block font-semibold">시·군·구</span>
          <select value={gu} onChange={(e) => setGu(e.target.value)} disabled={!sido} className="w-full rounded-lg border border-line bg-white px-2 py-2 disabled:text-muted">
            <option value={ALL}>{sido ? "전체" : "시·도를 먼저 고르세요"}</option>
            {districts.map((name) => (
              <option key={name}>{name}</option>
            ))}
          </select>
        </label>
      </div>

      <Summary title={`${title} · ${fees.label}`} values={values} national={title === "전국" ? null : fees.national} />
      <SidoChart fees={fees} chosen={sido} onChoose={chooseSido} />
      {sido ? <SigunguTable fees={fees} sido={sido} chosen={gu} onChoose={setGu} /> : null}

      <aside className="rounded-xl border border-warn/40 bg-warn/10 p-4 text-sm">
        <p className="font-semibold text-warn-strong">꼭 읽어 주세요</p>
        <ul className="mt-1 list-disc space-y-1 pl-5">
          <li>지역별 조사 통계이며 개별 병원의 가격이 아닙니다. 같은 항목도 병원의 인력·시설·장비에 따라 다릅니다.</li>
          <li>항목별 평일 주간 기준 금액입니다. 함께 받는 다른 진료·약·재료에 따라 실제 총비용은 달라집니다.</li>
          <li>병원이 1곳 이하이거나 해당 진료가 없는 지역은 공개되지 않습니다. 방문 전에 병원에 전화로 확인하세요.</li>
        </ul>
        <p className="mt-2 text-xs text-muted">
          출처:{" "}
          <a href={fees.source_url} target="_blank" rel="noreferrer" className="underline">
            {fees.source}
          </a>{" "}
          · 수집일 {fees.collected}
        </p>
      </aside>
    </div>
  );
}
