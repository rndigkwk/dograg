"use client";

import Link from "next/link";

import { LocateHospitals } from "./UrgentBox";

/** The emergency page's hospitals: the chat's own locate button (asks only on a tap, keeps nothing). */
export default function EmergencyHelp() {
  return (
    <>
      <LocateHospitals />
      <p className="mt-3 text-sm">
        위치를 쓰기 어렵다면 <Link href="/places" className="text-accent underline">병원·시설 찾기</Link>에서 지역으로 찾아보세요.
      </p>
    </>
  );
}
