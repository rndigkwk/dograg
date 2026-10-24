"use client";

import { useState } from "react";

import type { Emergency, Hospital } from "@/lib/chat";
import { locate, type Location } from "@/lib/location";
import { emergency } from "@/lib/places";

import Icon from "./Icon";

// The red warning an urgent sign puts above the answer, with the nearest hospitals or a button that finds them.

function HospitalLine({ row }: { row: Hospital }) {
  const digits = row.phone?.replace(/\D/g, "");
  return (
    <li>
      <strong>{row.name}</strong> · {row.distance_km.toFixed(1)}km ·{" "}
      {digits ? <a href={`tel:${digits}`}>{row.phone}</a> : "전화번호 없음"}
      <div className="text-sm text-muted">{row.road_address || row.lot_address || ""}</div>
    </li>
  );
}

/** Without a shared location the warning has no hospitals: its own button asks for the location and
 * fills them in here, without asking the question again (the button by the box below is far away). */
function LocateHospitals({ onLocated }: { onLocated?: (location: Location) => void }) {
  const [found, setFound] = useState<Emergency | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  async function find() {
    if (busy) return;
    setBusy(true);
    setNote("위치를 확인하는 중입니다…");
    const at = await locate();
    if (!("location" in at)) {
      setNote(`${at.error} 지역 이름으로 병원을 물어보거나 가까운 동물병원에 바로 연락하세요.`);
      setBusy(false);
      return;
    }
    onLocated?.(at.location);
    try {
      const hospitals = await emergency(at.location);
      setFound(hospitals);
      setNote(hospitals.nearest?.length ? null : "가까운 동물병원을 찾지 못했습니다. 지역 이름으로 병원을 물어보세요.");
    } catch {
      setNote("가까운 병원을 불러오지 못했습니다. 지역 이름으로 병원을 물어보거나 가까운 동물병원에 바로 연락하세요.");
    }
    setBusy(false);
  }
  if (found?.nearest?.length) return <HospitalLists hospitals={found} />;
  return (
    <>
      <button type="button" aria-disabled={busy} onClick={() => void find()} className="mt-2 inline-flex min-h-11 items-center rounded-lg bg-danger px-4 font-semibold text-white aria-disabled:opacity-60">
        <Icon name="locate" size={16} className="mr-1" />현재 위치로 가까운 병원 보기
      </button>
      <p role="status" className="mt-1 text-sm text-muted">{note ?? "버튼을 누를 때만 위치를 묻고, 저장하지 않습니다."}</p>
    </>
  );
}

function HospitalLists({ hospitals }: { hospitals: Emergency }) {
  return (
    <>
      <ul className="mt-1 space-y-1">{hospitals.nearest!.map((row) => <HospitalLine key={row.name} row={row} />)}</ul>
      {hospitals.night?.length ? (
        <>
          <p className="mt-2">이름에 24시·응급·야간이 들어간 가까운 병원</p>
          <ul className="mt-1 space-y-1">{hospitals.night.map((row) => <HospitalLine key={row.name} row={row} />)}</ul>
        </>
      ) : null}
      <p className="mt-2 text-sm text-muted">거리는 직선거리입니다. 영업 여부와 진료 시간은 데이터에 없으니 출발 전에 전화로 지금 진료가 가능한지 확인하세요.</p>
    </>
  );
}

export default function UrgentBox({ notice, hospitals, onLocated }: { notice: string; hospitals: Emergency; onLocated?: (location: Location) => void }) {
  return (
    <div role="alert" className="mb-3 rounded-lg border border-danger/40 bg-danger/5 p-3">
      <p className="font-semibold text-danger">{notice}</p>
      <p className="mt-2 font-semibold"><Icon name="alert" size={16} className="mr-1 inline-block align-[-3px]" />가까운 동물병원</p>
      {hospitals.nearest?.length ? <HospitalLists hospitals={hospitals} /> : <LocateHospitals onLocated={onLocated} />}
    </div>
  );
}
