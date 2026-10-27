"use client";

import { useEffect, useMemo, useState } from "react";

import {
  byMedian,
  DEFAULT_ITEM,
  type FeeItem,
  feeItems,
  type FeeValues,
  groupByCategory,
  type ItemFees,
  itemFees,
  shortSido,
  versusNational,
  won,
} from "@/lib/fees";
import { failureMessage } from "@/lib/failure";
import { districtGrid, PROVINCES, type TileGrid } from "@/lib/feeTiles";

import FeeSourceNotice from "./FeeSourceNotice";
import Waiting, { LoadError } from "./Waiting";

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

type Region = FeeValues & { name: string };

/** Regions as equal tiles laid out like the map (lib/feeTiles.ts), each with its name and median, as
 * animalclinicfee.or.kr labels its map. No colour by amount (2026-10-27): the medians mostly sit on
 * 1,000원 steps, so shades would say little; the numbers say it. Hover or focus reads a tile's mean and
 * range out; a click chooses it. */
function TileMap({ grid, regions, label, chosen, national, onChoose }: {
  grid: TileGrid;
  regions: Map<string, Region>;
  label: (name: string) => string;
  chosen: string;
  national: number;
  onChoose: (name: string) => void;
}) {
  const [active, setActive] = useState<string | null>(null);
  const shown = active ? regions.get(active) : undefined;
  return (
    <>
      <div
        role="group"
        aria-label="지도"
        className="grid justify-center gap-0.5 sm:gap-1.5"
        style={{ gridTemplateColumns: `repeat(${grid.columns}, minmax(0, ${grid.columns > 4 ? "6rem" : "7.5rem"}))` }}
      >
        {grid.tiles.map((tile) => {
          const region = regions.get(tile.name);
          const place = { gridColumn: tile.column + 1, gridRow: tile.row + 1 };
          if (!region)
            return (
              <div key={tile.name} style={place} className="rounded-lg border border-dashed border-line px-0 py-1.5 text-center text-[10px] leading-tight text-muted sm:py-2 sm:text-sm">
                <span className="block">{label(tile.name)}</span>
                <span className="block">자료 없음</span>
              </div>
            );
          const picked = chosen === tile.name;
          return (
            <button
              key={tile.name}
              type="button"
              style={place}
              onMouseEnter={() => setActive(tile.name)}
              onMouseLeave={() => setActive(null)}
              onFocus={() => setActive(tile.name)}
              onBlur={() => setActive(null)}
              onClick={() => onChoose(tile.name)}
              aria-pressed={picked}
              aria-label={`${tile.name} 중간값 ${won(region.median)}`}
              className={`rounded-lg border px-0 py-1.5 text-center text-[10px] leading-tight outline-none focus-visible:ring-2 focus-visible:ring-accent sm:py-2 sm:text-sm ${
                picked ? "border-accent bg-accent text-white" : "border-line bg-white hover:border-accent"
              }`}
            >
              <span className="block font-semibold">{label(tile.name)}</span>
              <span className="block tabular-nums">
                {region.median.toLocaleString("ko-KR")}
                <span className="hidden sm:inline">원</span>
              </span>
            </button>
          );
        })}
      </div>
      <p aria-live="polite" className="mt-3 min-h-5 text-sm text-muted">
        {shown
          ? `${shown.name}: 중간 ${won(shown.median)} · 평균 ${won(shown.mean)} · ${won(shown.min)} ~ ${won(shown.max)} (${versusNational(shown.median, national)})`
          : "칸에 마우스를 올리거나 Tab으로 옮기면 평균과 범위를 보여 줍니다."}
      </p>
    </>
  );
}

/** The same regions as a table, highest median first, for exact numbers and screen readers. */
function RegionTable({ heading, regions, chosen, onChoose }: { heading: string; regions: Region[]; chosen: string; onChoose: (name: string) => void }) {
  const rows = byMedian(regions);
  return (
    <details className="mt-1">
      <summary className="cursor-pointer text-sm text-accent">표로 보기</summary>
      <div className="mt-2 overflow-x-auto">
        <table className="w-full min-w-[24rem] text-left text-sm">
          <caption className="sr-only">{heading}</caption>
          <thead className="text-muted">
            <tr>
              <th className="py-1 pr-3">지역</th>
              <th className="py-1 pr-3 text-right">중간값</th>
              <th className="py-1 pr-3 text-right">평균</th>
              <th className="py-1 text-right">최저 ~ 최고</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr
                key={row.name}
                onClick={() => onChoose(row.name)}
                className={`cursor-pointer border-t border-line hover:bg-accent/5 ${chosen === row.name ? "bg-accent/10 font-semibold" : ""}`}
              >
                <td className="py-1 pr-3">{row.name}</td>
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
    </details>
  );
}

/** The map: the provinces, or the chosen province's cities and districts with a way back. */
function FeeMap({ fees, sido, gu, onSido, onGu }: { fees: ItemFees; sido: string; gu: string; onSido: (sido: string) => void; onGu: (gu: string) => void }) {
  const provinces = useMemo(() => new Map(fees.sido.map((row) => [row.sido, { ...row, name: row.sido }])), [fees.sido]);
  const districts = useMemo(
    () => new Map(fees.sigungu.filter((row) => row.sido === sido).map((row) => [row.sigungu, { ...row, name: row.sigungu }])),
    [fees.sigungu, sido],
  );
  const grid = sido ? districtGrid(sido) : PROVINCES;
  const province = provinces.get(sido);
  const chooseGu = (name: string) => onGu(gu === name ? ALL : name);
  return (
    <figure className="rounded-xl border border-line bg-white p-3 sm:p-4">
      <figcaption className="mb-3 flex flex-wrap items-center gap-x-2 gap-y-1">
        {sido ? (
          <button type="button" onClick={() => onSido(ALL)} className="rounded-lg border border-line px-2 py-0.5 text-sm">
            ← 전국 지도
          </button>
        ) : null}
        <span className="font-bold">{sido ? `${sido} 시·군·구별 중간값` : "시·도별 중간값"}</span>
        <span className="text-sm text-muted">
          전국 {won(fees.national.median)}
          {province ? ` · ${shortSido(sido)} ${won(province.median)}` : ""} · 단위 원 · {sido ? "칸을 누르면 그 시·군·구를 고릅니다" : "칸을 누르면 그 시·도의 시·군·구를 봅니다"}
        </span>
      </figcaption>
      {!grid || (sido && !districts.size) ? (
        <p className="text-sm text-muted">{sido}의 시·군·구 자료가 없습니다(병원이 1곳 이하인 지역은 공개되지 않습니다).</p>
      ) : sido ? (
        <TileMap key={sido} grid={grid} regions={districts} label={(name) => name} chosen={gu} national={fees.national.median} onChoose={chooseGu} />
      ) : (
        <TileMap grid={grid} regions={provinces} label={shortSido} chosen={sido} national={fees.national.median} onChoose={onSido} />
      )}
      {!sido && fees.no_data.length ? (
        <p className="mb-2 text-xs text-muted">자료 없음: {fees.no_data.map(shortSido).join(", ")} (해당 진료가 없거나 병원이 1곳 이하인 지역은 공개되지 않습니다)</p>
      ) : null}
      {sido ? (
        districts.size ? <RegionTable heading={`${sido} 시·군·구별 중간값`} regions={[...districts.values()]} chosen={gu} onChoose={chooseGu} /> : null
      ) : (
        <RegionTable heading="시·도별 중간값" regions={[...provinces.values()]} chosen={sido} onChoose={onSido} />
      )}
    </figure>
  );
}

/** The fee page: pick a surveyed item and a region; see that region's numbers, the provinces on a tile
 * map, and the chosen province's districts on its own map (animalclinicfee.or.kr's view). */
export type FeesStart = { items: FeeItem[]; fees: ItemFees };

export default function FeeExplorer({ initial = null }: { initial?: FeesStart | null }) {
  const [items, setItems] = useState<FeeItem[] | null>(initial?.items ?? null);
  const [itemLabel, setItemLabel] = useState(initial?.fees.label ?? DEFAULT_ITEM);
  const [fees, setFees] = useState<ItemFees | null>(initial?.fees ?? null);
  const [sido, setSido] = useState(ALL);
  const [gu, setGu] = useState(ALL);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (initial && attempt === 0) return; // drawn from the server (lib/prefetch.ts)
    feeItems().then((body) => setItems(body.items), (e: Error) => setError(failureMessage(e, e.message)));
  }, [attempt, initial]);

  const item = items?.find((candidate) => candidate.label === itemLabel) ?? items?.[0];
  useEffect(() => {
    if (!item) return;
    // The server's figures are for the first item; another item or a retry fetches.
    if (initial && attempt === 0 && item.item === initial.fees.item && item.detail === initial.fees.detail) return;
    let current = true;
    itemFees(item).then(
      (body) => current && setFees(body),
      (e: Error) => current && setError(failureMessage(e, e.message)),
    );
    return () => {
      current = false;
    };
  }, [item, attempt, initial]);

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
      <FeeSourceNotice />
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
      <FeeMap fees={fees} sido={sido} gu={gu} onSido={chooseSido} onGu={setGu} />

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
