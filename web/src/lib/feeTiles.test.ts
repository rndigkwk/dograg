import { describe, expect, it } from "vitest";

import DISTRICTS from "./feeTiles.json";
import { districtGrid, PROVINCES, type TileGrid } from "./feeTiles";

function cellsAreOwn(grid: TileGrid) {
  const cells = grid.tiles.map((tile) => `${tile.column},${tile.row}`);
  expect(new Set(cells).size).toBe(cells.length);
  for (const tile of grid.tiles) {
    expect(tile.column).toBeGreaterThanOrEqual(0);
    expect(tile.column).toBeLessThan(grid.columns);
    expect(tile.row).toBeGreaterThanOrEqual(0);
    expect(tile.row).toBeLessThan(grid.rows);
  }
}

describe("fee tile maps", () => {
  it("has every surveyed province once, each in its own cell", () => {
    expect(PROVINCES.tiles.map((tile) => tile.name).sort()).toEqual(Object.keys(DISTRICTS).sort());
    cellsAreOwn(PROVINCES);
  });

  it("gives every province's districts their own cells", () => {
    for (const name of Object.keys(DISTRICTS)) cellsAreOwn(districtGrid(name)!);
    expect(districtGrid("서울특별시")!.tiles).toHaveLength(25);
    expect(districtGrid("없는도")).toBeNull();
  });

  it("keeps a neighbour on its side: 강남구 east of 강서구, 도봉구 north of 관악구", () => {
    const seoul = Object.fromEntries(districtGrid("서울특별시")!.tiles.map((tile) => [tile.name, tile]));
    expect(seoul["강남구"].column).toBeGreaterThan(seoul["강서구"].column);
    expect(seoul["도봉구"].row).toBeLessThan(seoul["관악구"].row);
  });
});
