// The fee page's tile maps: the provinces of Korea, then a chosen province's cities and districts,
// each an equal tile near where it is (animalclinicfee.or.kr labels the same regions on a map).
// Equal tiles, not a drawn map: 세종·대전·광주 would be too small to tap on a real one.

import DISTRICTS from "./feeTiles.json";

export type Tile = { name: string; column: number; row: number };
export type TileGrid = { columns: number; rows: number; tiles: Tile[] };

// The 17 provinces by hand, north at the top, west at the left.
export const PROVINCES: TileGrid = {
  columns: 4,
  rows: 7,
  tiles: [
    { name: "경기도", column: 1, row: 0 },
    { name: "인천광역시", column: 0, row: 1 },
    { name: "서울특별시", column: 1, row: 1 },
    { name: "강원특별자치도", column: 2, row: 1 },
    { name: "충청남도", column: 0, row: 2 },
    { name: "세종특별자치시", column: 1, row: 2 },
    { name: "충청북도", column: 2, row: 2 },
    { name: "전북특별자치도", column: 0, row: 3 },
    { name: "대전광역시", column: 1, row: 3 },
    { name: "경상북도", column: 2, row: 3 },
    { name: "광주광역시", column: 0, row: 4 },
    { name: "경상남도", column: 1, row: 4 },
    { name: "대구광역시", column: 2, row: 4 },
    { name: "울산광역시", column: 3, row: 4 },
    { name: "전라남도", column: 0, row: 5 },
    { name: "부산광역시", column: 2, row: 5 },
    { name: "제주특별자치도", column: 0, row: 6 },
  ],
};

/** A province's cities and districts (scripts/build_fee_tiles.py), or null for one not surveyed. */
export function districtGrid(sido: string): TileGrid | null {
  return (DISTRICTS as Record<string, TileGrid>)[sido] ?? null;
}
