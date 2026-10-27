import { describe, expect, it } from "vitest";

import { categoriesOf, directionsUrl, filterPlaces, type Place } from "./places";

const at = (id: string, name: string, category: string | null, address: string | null = null, coords = true): Place => ({
  id, kind: "pet_friendly", name, address, phone: null, homepage: null, category,
  latitude: coords ? 37.55 : null, longitude: coords ? 126.91 : null, info: {}, info_lines: [],
});
const places = [at("1", "멍멍 카페", "카페", "서울 마포구 연남동"), at("2", "바다 펜션", "펜션", "강원 속초시"), at("3", "숲 카페", "카페", "서울 마포구 망원동")];

describe("filterPlaces", () => {
  it("narrows by every word of the name or address, and by the category", () => {
    expect(filterPlaces(places, "마포 카페", "").map((p) => p.id)).toEqual(["1", "3"]);
    expect(filterPlaces(places, "  망원 ", "카페").map((p) => p.id)).toEqual(["3"]);
    expect(filterPlaces(places, "", "펜션").map((p) => p.id)).toEqual(["2"]);
    expect(filterPlaces(places, "", "")).toHaveLength(3);
  });
});

describe("categoriesOf", () => {
  it("lists the categories most common first", () => {
    expect(categoriesOf([...places, at("4", "무명", null)])).toEqual(["카페", "펜션"]);
  });
});

describe("directionsUrl", () => {
  it("goes to Kakao Map with the name and the coordinates, or nowhere without them", () => {
    expect(directionsUrl(at("1", "멍멍, 카페", "카페"))).toBe(`https://map.kakao.com/link/to/${encodeURIComponent("멍멍  카페")},37.55,126.91`);
    expect(directionsUrl(at("9", "좌표 없음", null, null, false))).toBeNull();
  });
});
