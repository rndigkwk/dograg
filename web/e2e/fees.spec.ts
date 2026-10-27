import { expect, test } from "@playwright/test";

import { fakeApi } from "./fake-api";

const ITEMS = {
  items: [
    { category: "진찰료", item: "초진 진찰료", detail: "체중 5kg", label: "초진 진찰료 (체중 5kg)" },
    { category: "영상검사비용", item: "자기공명영상검사(MRI)비와 판독료", detail: "체중 5kg", label: "자기공명영상검사(MRI)비와 판독료 (체중 5kg)" },
  ],
  source: "농림축산식품부 동물병원 진료비 현황 조사(2025, animalclinicfee.or.kr)",
  notice: "지역별 조사 통계이며 개별 병원의 가격이 아닙니다.",
};

const fees = (url: URL) => {
  const mri = url.searchParams.get("item")?.startsWith("자기공명");
  const v = (median: number) => ({ mean: median, median, min: median / 2, max: median * 2 });
  return {
    item: url.searchParams.get("item"),
    detail: url.searchParams.get("detail"),
    category: mri ? "영상검사비용" : "진찰료",
    label: mri ? "자기공명영상검사(MRI)비와 판독료 (체중 5kg)" : "초진 진찰료 (체중 5kg)",
    national: v(mri ? 750000 : 10000),
    sido: [
      { sido: "서울특별시", ...v(mri ? 800000 : 11000) },
      { sido: "경기도", ...v(mri ? 775000 : 9000) },
    ],
    sigungu: [
      { sido: "서울특별시", sigungu: "강남구", ...v(mri ? 900000 : 15000) },
      { sido: "서울특별시", sigungu: "강동구", ...v(mri ? 700000 : 9500) },
    ],
    no_data: mri ? ["세종특별자치시"] : [],
    collected: "2026-10-10",
    source: ITEMS.source,
    source_url: "https://animalclinicfee.or.kr/info/payInfo.do",
    notice: ITEMS.notice,
  };
};

test("the fee page shows the provinces on a tile map, then a province's districts", async ({ page }) => {
  const api = await fakeApi(page, [], { "/fees/items": ITEMS, "/fees": fees });
  await page.goto("/fees");
  await expect(page.getByRole("region", { name: "전국 · 초진 진찰료 (체중 5kg) 진료비" })).toContainText("10,000원");
  const map = page.getByRole("group", { name: "지도" });
  // The provinces as tiles with their names and medians; one without a figure says so, not 0원.
  await expect(map.getByRole("button")).toHaveCount(2);
  await expect(map.getByRole("button", { name: "서울특별시 중간값 11,000원" })).toContainText("서울11,000원");
  await expect(map).toContainText("부산자료 없음");

  // A tile opens its province's districts: the summary follows, and a district tile chooses it.
  await map.getByRole("button", { name: "서울특별시 중간값 11,000원" }).click();
  await expect(page.getByRole("region", { name: "서울특별시 · 초진 진찰료 (체중 5kg) 진료비" })).toContainText("전국보다 1,000원 높음");
  await expect(map.getByRole("button")).toHaveCount(2);
  await expect(map).toContainText("종로구자료 없음");
  await map.getByRole("button", { name: "강동구 중간값 9,500원" }).click();
  await expect(page.getByRole("region", { name: "서울특별시 강동구 · 초진 진찰료 (체중 5kg) 진료비" })).toContainText("9,500원");
  await page.getByText("표로 보기").click();
  await expect(page.getByRole("row").nth(1)).toContainText("강남구");

  // Back to the provinces.
  await page.getByRole("button", { name: "← 전국 지도" }).click();
  await expect(page.getByRole("region", { name: "전국 · 초진 진찰료 (체중 5kg) 진료비" })).toBeVisible();
  await expect(map.getByRole("button", { name: "경기도 중간값 9,000원" })).toBeVisible();

  // Another item: a province with no figure is named, not drawn as 0원.
  await page.getByRole("combobox", { name: "진료 항목" }).selectOption("자기공명영상검사(MRI)비와 판독료 (체중 5kg)");
  await expect(page.getByText("자료 없음: 세종")).toBeVisible();
  expect(api.gets).toContain(`/fees?${new URLSearchParams({ item: "자기공명영상검사(MRI)비와 판독료", detail: "체중 5kg" })}`);
  await expect(page.getByRole("link", { name: ITEMS.source })).toHaveAttribute("href", "https://animalclinicfee.or.kr/info/payInfo.do");
});
