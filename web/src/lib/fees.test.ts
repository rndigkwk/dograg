import { describe, expect, it } from "vitest";

import { byMedian, gapLabel, groupByCategory, shortSido, versusNational, won } from "./fees";

describe("fees", () => {
  it("shortens province names like the survey site", () => {
    expect(["서울특별시", "세종특별자치시", "제주특별자치도", "강원특별자치도", "경기도", "전북특별자치도", "충청남도", "부산광역시"].map(shortSido)).toEqual([
      "서울",
      "세종",
      "제주",
      "강원",
      "경기",
      "전북",
      "충남",
      "부산",
    ]);
  });

  it("ranks provinces by median, then by name", () => {
    const row = (sido: string, median: number) => ({ sido, median, mean: median, min: 0, max: median });
    expect(byMedian([row("대구광역시", 9000), row("강원특별자치도", 10000), row("경기도", 9000)]).map((r) => r.sido)).toEqual([
      "강원특별자치도",
      "경기도",
      "대구광역시",
    ]);
  });

  it("says how a price compares with the national one", () => {
    expect(won(10000)).toBe("10,000원");
    expect(versusNational(11000, 10000)).toBe("전국보다 1,000원 높음");
    expect(versusNational(8500, 10000)).toBe("전국보다 1,500원 낮음");
    expect(versusNational(10000, 10000)).toBe("전국과 같음");
    expect([gapLabel(11000, 10000), gapLabel(9500, 10000), gapLabel(10000, 10000)]).toEqual(["+1,000", "−500", "±0"]);
  });

  it("groups items by category in order", () => {
    const item = (category: string, label: string) => ({ category, item: label, detail: "", label });
    expect(groupByCategory([item("진찰료", "초진"), item("진찰료", "재진"), item("입원비", "입원")]).map(([c, i]) => [c, i.length])).toEqual([
      ["진찰료", 2],
      ["입원비", 1],
    ]);
  });
});
