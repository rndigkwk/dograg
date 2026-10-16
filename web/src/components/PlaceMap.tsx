"use client";

import "leaflet/dist/leaflet.css";

import { CircleMarker, MapContainer, TileLayer, Tooltip, useMap } from "react-leaflet";
import { useEffect } from "react";

import { located, type Place } from "@/lib/places";

/** Zooms to the places when they change (not on every render: the user may have moved the map). */
function Fit({ points }: { points: [number, number][] }) {
  const map = useMap();
  const key = JSON.stringify(points);
  useEffect(() => {
    const shown: [number, number][] = JSON.parse(key);
    if (shown.length === 1) map.setView(shown[0], 16);
    else if (shown.length > 1) map.fitBounds(shown, { padding: [24, 24], maxZoom: 15 });
  }, [map, key]);
  return null;
}

/** The places on an OpenStreetMap map; loaded only in the browser (Leaflet needs `window`). */
export default function PlaceMap({ places }: { places: Place[] }) {
  const shown = located(places);
  if (!shown.length) return <p className="text-sm text-muted">지도에 표시할 수 있는 좌표 정보가 없습니다.</p>;
  const points = shown.map((p) => [p.latitude, p.longitude] as [number, number]);
  return (
    <div role="region" aria-label="시설 지도">
      {/* The mouse wheel over the map zooms it (user request 2026-10-16); outside the map the page scrolls. */}
      <MapContainer center={points[0]} zoom={13} scrollWheelZoom wheelPxPerZoomLevel={120} className="h-80 w-full rounded-xl border border-line">
        <TileLayer attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>' url="https://tile.openstreetmap.org/{z}/{x}/{y}.png" />
        {shown.map((p) => (
          <CircleMarker key={p.id} center={[p.latitude, p.longitude]} radius={7} pathOptions={{ color: "#c62828", fillOpacity: 0.7 }}>
            <Tooltip>
              {p.name}
              <br />
              {p.address}
            </Tooltip>
          </CircleMarker>
        ))}
        <Fit points={points} />
      </MapContainer>
    </div>
  );
}
