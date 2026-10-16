"use client";

import dynamic from "next/dynamic";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";

import { locate, type Location } from "@/lib/location";
import { type Kind, kinds as loadKinds, nearby, type Place, place as loadPlace, regions as loadRegions, search, TABLE_INFO } from "@/lib/places";

const PlaceMap = dynamic(() => import("./PlaceMap"), { ssr: false, loading: () => <p className="text-sm text-muted">지도를 불러오는 중입니다…</p> });

function PlaceTable({ places, withDistance = false }: { places: Place[]; withDistance?: boolean }) {
  const details = places.some((p) => p.kind === "pet_friendly");
  return (
    <div className="overflow-x-auto rounded-xl border border-line bg-white">
      <table className="w-full min-w-[36rem] text-left text-sm">
        <thead className="bg-page text-muted">
          <tr>
            <th className="px-3 py-2">이름</th>
            <th className="px-3 py-2">주소</th>
            <th className="px-3 py-2">전화번호</th>
            {details ? TABLE_INFO.map(([key, label]) => <th key={key} className="px-3 py-2">{label}</th>) : null}
            {withDistance ? <th className="px-3 py-2">직선거리</th> : null}
          </tr>
        </thead>
        <tbody>
          {places.map((p) => (
            <tr key={p.id} className="border-t border-line">
              <td className="px-3 py-2">
                <Link href={`/places?id=${encodeURIComponent(p.id)}`} className="text-accent underline">
                  {p.name}
                </Link>
                {p.category ? <div className="text-xs text-muted">{p.category}</div> : null}
              </td>
              <td className="px-3 py-2">{p.address ?? "주소 없음"}</td>
              <td className="px-3 py-2 whitespace-nowrap">{p.phone ? <a href={`tel:${p.phone.replace(/\D/g, "")}`}>{p.phone}</a> : ""}</td>
              {details ? TABLE_INFO.map(([key]) => <td key={key} className="px-3 py-2">{p.info[key] ?? ""}</td>) : null}
              {withDistance ? <td className="px-3 py-2 whitespace-nowrap">{p.distance_km?.toFixed(2)}km</td> : null}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** One place, opened from a list or from a chat answer (app_pages/hospital.py render_selected_place). */
function PlaceView({ id }: { id: string }) {
  const [found, setFound] = useState<Place | null | "missing">(null);
  useEffect(() => {
    loadPlace(id).then(setFound, () => setFound("missing"));
  }, [id]);
  if (found === null) return <p className="text-muted">불러오는 중입니다…</p>;
  if (found === "missing") return <p role="alert" className="text-danger">선택한 장소를 찾지 못했습니다.</p>;
  return (
    <article className="space-y-2">
      <h2 className="text-xl font-bold">{found.name}</h2>
      <p>{found.address ?? "주소 없음"}</p>
      {found.category ? <p className="text-sm text-muted">{found.category}</p> : null}
      {found.phone ? <p>전화번호: <a href={`tel:${found.phone.replace(/\D/g, "")}`}>{found.phone}</a></p> : null}
      {found.homepage ? <p><a href={found.homepage} target="_blank" rel="noreferrer" className="text-accent underline">홈페이지</a></p> : null}
      {found.info_lines.map((line) => <p key={line}>{line}</p>)}
      <PlaceMap places={[found]} />
    </article>
  );
}

export default function Places() {
  const params = useSearchParams();
  const selected = params.get("id");
  const [kinds, setKinds] = useState<Kind[]>([]);
  const [regionList, setRegionList] = useState<Record<string, string[]>>({});
  const [kind, setKind] = useState("hospital");
  const [province, setProvince] = useState("");
  const [city, setCity] = useState("");
  const [location, setLocation] = useState<Location | null>(null);
  const [near, setNear] = useState<Place[] | null>(null);
  const [found, setFound] = useState<{ total: number; places: Place[]; area: string } | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    Promise.all([loadKinds(), loadRegions()]).then(
      ([k, r]) => {
        setKinds(k);
        setRegionList(r);
        const first = Object.keys(r)[0] ?? "";
        setProvince(first);
        setCity(r[first]?.[0] ?? "");
      },
      () => setError("시설 정보를 불러오지 못했습니다. 잠시 뒤 다시 시도해 주세요."),
    );
  }, []);

  const current = kinds.find((k) => k.kind === kind);
  const label = current?.label ?? "시설";
  const byCity = kind !== "funeral"; // the funeral list names provinces only

  async function findNear(at: Location | null = location) {
    if (!at || !current?.has_location) return;
    setBusy(true);
    try {
      setNear((await nearby(kind, at)).places);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function useLocation() {
    setNote("위치를 확인하는 중입니다…");
    const result = await locate();
    if ("location" in result) {
      setLocation(result.location);
      setNote(null);
      await findNear(result.location);
    } else setNote(`${result.error} 아래 지역 검색은 계속 사용할 수 있습니다.`);
  }

  async function findInRegion(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const result = await search(kind, province, byCity ? city : undefined);
      setFound({ ...result, area: byCity ? `${province} ${city}` : province });
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (selected) {
    return (
      <div className="space-y-4">
        <Link href="/places" className="text-sm text-accent underline">← 다른 장소 찾기</Link>
        <PlaceView id={selected} />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <fieldset>
        <legend className="mb-2 font-semibold">찾을 곳</legend>
        <div className="flex flex-wrap gap-2">
          {kinds.map((k) => (
            <label key={k.kind} className={`cursor-pointer rounded-full border px-3 py-1 text-sm ${k.kind === kind ? "border-accent bg-accent text-white" : "border-line bg-white"}`}>
              <input
                type="radio"
                name="kind"
                value={k.kind}
                checked={k.kind === kind}
                onChange={() => {
                  setKind(k.kind);
                  setNear(null);
                  setFound(null);
                }}
                className="sr-only"
              />
              {k.label}
            </label>
          ))}
        </div>
        {current?.source ? (
          <p className="mt-2 text-xs text-muted">
            출처:{" "}
            <a href={current.source.url} target="_blank" rel="noreferrer" className="underline">
              {current.source.title}
            </a>{" "}
            · {current.source.rows.toLocaleString()}곳 · 데이터 기준 {current.source.updated.slice(0, 10)}. 공공데이터라서 실제 영업 여부·영업시간·이용 조건은 방문 전 전화로 확인해 주세요.
          </p>
        ) : null}
      </fieldset>

      {error ? <p role="alert" className="text-danger">{error}</p> : null}

      <section className="space-y-2" aria-label="가까운 곳">
        {current && !current.has_location ? (
          <p className="rounded-lg bg-accent/5 p-3 text-sm">{label} 목록에는 좌표가 없어 현재 위치 검색은 지원하지 않고, 지역으로만 찾을 수 있습니다.</p>
        ) : (
          <>
            <h2 className="text-lg font-bold">현재 위치에서 가까운 {label}</h2>
            <p className="text-sm text-muted">버튼을 누를 때만 위치 권한을 요청합니다. 거리는 직선거리이며 이동거리·소요시간과 다릅니다.</p>
            <button type="button" disabled={busy} onClick={location ? () => findNear() : useLocation} className="rounded-lg border border-line bg-white px-3 py-1 disabled:opacity-40">
              📍 {location ? `가까운 ${label} 다시 찾기` : "현재 위치 사용"}
            </button>
            {note ? <p className="text-sm text-muted">{note}</p> : null}
            {near ? (
              near.length ? (
                <>
                  <PlaceTable places={near} withDistance />
                  <PlaceMap places={near} />
                </>
              ) : (
                <p className="text-warn-strong">위치 좌표가 유효한 {label} 정보를 찾지 못했습니다.</p>
              )
            ) : null}
          </>
        )}
      </section>

      <section className="space-y-2" aria-label="지역 검색">
        <h2 className="text-lg font-bold">검색할 지역을 선택하세요.</h2>
        <form onSubmit={findInRegion} className="flex flex-wrap items-end gap-2">
          <label className="text-sm">
            시/도
            <select
              value={province}
              onChange={(event) => {
                setProvince(event.target.value);
                setCity(regionList[event.target.value]?.[0] ?? "");
              }}
              className="block rounded-lg border border-line bg-white px-2 py-1"
            >
              {Object.keys(regionList).map((name) => <option key={name}>{name}</option>)}
            </select>
          </label>
          {byCity ? (
            <label className="text-sm">
              시/군/구
              <select value={city} onChange={(event) => setCity(event.target.value)} className="block rounded-lg border border-line bg-white px-2 py-1">
                {(regionList[province] ?? []).map((name) => <option key={name}>{name}</option>)}
              </select>
            </label>
          ) : null}
          <button type="submit" disabled={busy || !province} className="rounded-lg bg-accent px-4 py-1.5 font-semibold text-white disabled:opacity-40">
            조회
          </button>
        </form>
        {found ? (
          found.total ? (
            <>
              <p role="status" className="text-sm">
                {found.area} 지역에서 {label} {found.total.toLocaleString()}곳을 찾았습니다.
                {found.total > found.places.length ? ` 앞의 ${found.places.length.toLocaleString()}곳을 보여 줍니다.` : ""}
              </p>
              <PlaceTable places={found.places} />
              <PlaceMap places={found.places} />
            </>
          ) : (
            <p role="status" className="text-warn-strong">{found.area} 지역의 {label} 정보를 찾지 못했습니다.</p>
          )
        ) : null}
      </section>
    </div>
  );
}
