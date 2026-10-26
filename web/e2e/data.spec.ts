import { expect, test } from "@playwright/test";

import { fakeApi } from "./fake-api";

const OVERVIEW = {
  diseases: [
    { label: "중성화수술", count: 579 },
    { label: "무릎뼈 탈구", count: 517 },
  ],
  departments: [
    { label: "내과", count: 9846 },
    { label: "외과", count: 5107 },
  ],
  hospitals_by_province: [{ label: "경기도", count: 1403 }],
  place_sources: [
    {
      kind: "hospital",
      label: "동물병원",
      title: "행정안전부 동물병원 인허가 정보",
      url: "https://www.data.go.kr",
      source_rows: 10596,
      rows: 5459,
      with_location: 5243,
      with_phone: 3031,
      updated: "2026-08-11 22:02:01",
      notes: ["영업/정상만 사용", "좌표 변환"],
    },
  ],
};

test("the data page shows the counts as bars, with shares and a table", async ({ page }) => {
  await fakeApi(page, [], { "/stats/overview": OVERVIEW });
  await page.goto("/data");
  // The first tab says what the project is; the charts follow.
  await expect(page.getByRole("heading", { name: "라그도그는 무엇인가요" })).toBeVisible();
  await expect(page.getByRole("link", { name: /GitHub에서 코드 보기/ })).toHaveAttribute("href", "https://github.com/rndigkwk/dograg");
  await page.getByRole("tab", { name: "기타를 제외한 질병 순위" }).click();
  const chart = page.getByRole("list", { name: "기타를 제외한 질병 분류 TOP 10" });
  await expect(chart.getByRole("listitem")).toHaveCount(2);
  await expect(chart.getByRole("listitem").first()).toContainText("579");

  await page.getByRole("tab", { name: "진료과 별 분포" }).click();
  await page.getByRole("listitem", { name: "내과 9,846건" }).hover();
  await expect(page.getByText("내과: 9,846건 (전체의 65.8%)")).toBeVisible();
  await page.getByText("표로 보기").click();
  await expect(page.getByRole("cell", { name: "5,107" })).toBeVisible();
  await expect(page.getByRole("cell", { name: "34.2%" })).toBeVisible(); // 5107 / (9846 + 5107)

  await page.getByRole("tab", { name: "반려동물 시설 데이터" }).click();
  await expect(page.getByText("원본 10,596행 중", { exact: false })).toBeVisible();
  await expect(page.getByRole("cell", { name: "96%" })).toBeVisible(); // with coordinates: 5243 / 5459
  await expect(page.getByRole("listitem", { name: "동물병원 5,459곳" })).toBeVisible(); // the kinds as bars

  await page.getByRole("tab", { name: "데이터 출처" }).click();
  await expect(page.getByRole("link", { name: "반려견 성장 및 질병관련 말뭉치 데이터" })).toHaveAttribute("href", /aihub\.or\.kr/);
  await expect(page.getByRole("link", { name: "행정안전부 동물병원 인허가 정보" })).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBe(0);
});

test("the data page says so when the numbers cannot be loaded", async ({ page }) => {
  await fakeApi(page, []); // /stats/overview answers 404
  await page.goto("/data");
  await expect(page.getByRole("alert").filter({ hasText: "데이터 수치를 불러오지 못했습니다" })).toBeVisible();
});
