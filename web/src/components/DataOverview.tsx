"use client";

import { useEffect, useState } from "react";

import { type Overview, overview, percent } from "@/lib/stats";

import { failureMessage } from "@/lib/failure";

import { DataSources, ProjectAbout } from "./AboutTabs";
import BarChart from "./BarChart";
import DonutChart from "./DonutChart";
import Waiting, { LoadError } from "./Waiting";

const TABS = ["프로젝트 소개", "기타를 제외한 질병 순위", "진료과 별 분포", "지역별 동물병원 수", "반려동물 시설 데이터", "데이터 출처"] as const;

function PlaceSources({ sources }: { sources: Overview["place_sources"] }) {
  const sourceRows = sources.reduce((sum, s) => sum + s.source_rows, 0);
  const rows = sources.reduce((sum, s) => sum + s.rows, 0);
  // One bar a kind: 반려동물 동반 시설 comes from two sources (문화정보원, 한국관광공사).
  const byKind = new Map<string, number>();
  for (const s of sources) byKind.set(s.label, (byKind.get(s.label) ?? 0) + s.rows);
  return (
    <div className="space-y-4">
      <BarChart
        title="종류별 시설 수"
        unit="곳"
        rows={[...byKind].sort((a, b) => b[1] - a[1]).map(([label, count]) => ({ label, count }))}
        note="시설 찾기에서 쓰는 수"
      />
      <div className="space-y-4 rounded-xl border border-line bg-white p-4">
        <p>
          공공데이터 {sources.length}종을 하나의 시설 DB로 정리했습니다. 원본 {sourceRows.toLocaleString()}행 중{" "}
          <strong>{rows.toLocaleString()}곳</strong>을 서비스에 사용합니다.
        </p>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[40rem] text-left text-sm">
            <thead className="text-muted">
              <tr>
                <th className="py-1 pr-3">종류</th>
                <th className="py-1 pr-3">출처</th>
                <th className="py-1 pr-3 text-right">원본 행</th>
                <th className="py-1 pr-3 text-right">사용</th>
                <th className="py-1 pr-3 text-right">좌표 보유</th>
                <th className="py-1 pr-3 text-right">전화번호 보유</th>
                <th className="py-1">데이터 기준일</th>
              </tr>
            </thead>
            <tbody>
              {sources.map((s) => (
                <tr key={s.kind} className="border-t border-line">
                  <td className="py-1 pr-3">{s.label}</td>
                  <td className="py-1 pr-3">
                    <a href={s.url} target="_blank" rel="noreferrer" className="underline">{s.title}</a>
                  </td>
                  <td className="py-1 pr-3 text-right tabular-nums">{s.source_rows.toLocaleString()}</td>
                  <td className="py-1 pr-3 text-right tabular-nums">{s.rows.toLocaleString()}</td>
                  <td className="py-1 pr-3 text-right tabular-nums">{percent(s.with_location, s.rows)}</td>
                  <td className="py-1 pr-3 text-right tabular-nums">{percent(s.with_phone, s.rows)}</td>
                  <td className="py-1 tabular-nums">{s.updated.slice(0, 10)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <h3 className="font-bold">정제 과정</h3>
        <ul className="list-disc space-y-1 pl-5 text-sm">
          {sources.map((s) => (
            <li key={s.kind}>
              <strong>{s.label}</strong>: {s.notes.join(" · ")}
            </li>
          ))}
        </ul>
        <p className="text-xs text-muted">
          좌표는 EPSG:5174(중부원점 TM)에서 WGS84로 변환하고 대한민국 범위(위도 33~39, 경도 124~132)를 벗어난 값은 버렸습니다. 주소의 시·도 이름은 현재
          행정구역 이름으로 통일했습니다.
        </p>
      </div>
    </div>
  );
}

/** The 소개 page (/data): the project, the consultation counts, the place data and every source, in six tabs. */
export default function DataOverview({ initial = null }: { initial?: Overview | null }) {
  const [data, setData] = useState<Overview | null>(initial);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState(0);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (initial && attempt === 0) return; // drawn from the server (lib/prefetch.ts)
    overview().then(setData, (e: Error) => setError(failureMessage(e, e.message)));
  }, [attempt, initial]);

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
  if (!data) return <Waiting text="데이터를 불러오는 중입니다…" />;

  const panels = [
    <ProjectAbout key="a" />,
    <BarChart key="d" title="기타를 제외한 질병 분류 TOP 10" unit="건" rows={data.diseases} note="상담 데이터 개수" />,
    <DonutChart key="p" title="진료과별 상담 비율" unit="건" rows={data.departments} note="상담 데이터의 진료과 라벨" />,
    <BarChart key="h" title="도로명주소 기준 시·도별 동물병원 수" unit="곳" rows={data.hospitals_by_province} />,
    <PlaceSources key="s" sources={data.place_sources} />,
    <DataSources key="o" places={data.place_sources} />,
  ];
  return (
    <div>
      {/* Tabs as the ARIA pattern: one Tab stop, arrows (and Home/End) move between them. */}
      <div
        role="tablist"
        aria-label="데이터 종류"
        className="mb-4 flex gap-1 overflow-x-auto border-b border-line"
        onKeyDown={(event) => {
          const last = TABS.length - 1;
          const next = { ArrowRight: tab === last ? 0 : tab + 1, ArrowLeft: tab === 0 ? last : tab - 1, Home: 0, End: last }[event.key];
          if (next === undefined) return;
          event.preventDefault();
          setTab(next);
          document.getElementById(`tab-${next}`)?.focus();
        }}
      >
        {TABS.map((label, index) => (
          <button
            key={label}
            type="button"
            role="tab"
            id={`tab-${index}`}
            aria-selected={tab === index}
            tabIndex={tab === index ? 0 : -1}
            aria-controls={`panel-${index}`}
            onClick={() => setTab(index)}
            className={`shrink-0 border-b-2 px-3 py-2 text-sm ${tab === index ? "border-accent font-semibold text-accent" : "border-transparent text-muted"}`}
          >
            {label}
          </button>
        ))}
      </div>
      <div role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`} tabIndex={0}>
        {panels[tab]}
      </div>
    </div>
  );
}
