import { expect, test } from "@playwright/test";
import { openFromMenu } from "./nav";

import { ask, fakeApi, result } from "./fake-api";

const source = { title: "행정안전부 동물병원 인허가 정보", url: "https://www.data.go.kr", rows: 5459, updated: "2026-08-11 22:02:01" };
const hospital = (n: number, extra = {}) => ({
  id: `hospital-${n}`,
  kind: "hospital",
  name: `강남동물병원${n}`,
  address: `서울특별시 강남구 테헤란로 ${n}`,
  phone: "02-123-4567",
  homepage: null,
  category: null,
  latitude: 37.5 + n / 1000,
  longitude: 127.03,
  info: {},
  info_lines: [],
  ...extra,
});
const PLACES = {
  "/places/kinds": [
    { kind: "hospital", label: "동물병원", has_location: true, source },
    { kind: "funeral", label: "장묘업체", has_location: false, source: null },
  ],
  "/places/regions": { 서울특별시: ["강남구", "서초구"], 부산광역시: ["해운대구"] },
  "/places/search": (url: URL) => ({ total: url.searchParams.get("city") === "서초구" ? 0 : 2, places: url.searchParams.get("city") === "서초구" ? [] : [hospital(1), hospital(2)] }),
  "/places/nearby": { places: [hospital(1, { distance_km: 0.42 })] },
  "/places/hospital-1": hospital(1, { info_lines: ["운영시간: 매일 09:00~21:00"] }),
};

test("places are found by region and opened on the map", async ({ page }) => {
  const api = await fakeApi(page, [], PLACES);
  await page.goto("/places");
  await expect(page.getByText("출처:", { exact: false })).toContainText("5,459곳");
  await page.getByLabel("시/군/구").selectOption("강남구");
  await page.getByRole("button", { name: "조회" }).click();
  await expect(page.getByRole("status")).toContainText("서울특별시 강남구 지역에서 동물병원 2곳을 찾았습니다.");
  await expect(page.getByRole("region", { name: "시설 지도" })).toBeVisible();
  expect(api.gets).toContain("/places/search?kind=hospital&province=%EC%84%9C%EC%9A%B8%ED%8A%B9%EB%B3%84%EC%8B%9C&city=%EA%B0%95%EB%82%A8%EA%B5%AC&limit=1000");

  await page.getByRole("link", { name: "강남동물병원1" }).click();
  await expect(page).toHaveURL(/\/places\?id=hospital-1$/);
  await expect(page.getByRole("heading", { name: "강남동물병원1" })).toBeVisible();
  await expect(page.getByText("운영시간: 매일 09:00~21:00")).toBeVisible();
  await page.getByRole("link", { name: "← 다른 장소 찾기" }).click();
  await page.getByLabel("시/군/구").selectOption("서초구");
  await page.getByRole("button", { name: "조회" }).click();
  await expect(page.getByRole("status")).toContainText("서울특별시 서초구 지역의 동물병원 정보를 찾지 못했습니다.");
});

test("the nearest places use the browser's position; kinds without coordinates search by province", async ({ page, context }) => {
  await context.grantPermissions(["geolocation"]);
  await context.setGeolocation({ latitude: 37.5, longitude: 127.03 });
  const api = await fakeApi(page, [], PLACES);
  await page.goto("/places");
  await page.getByRole("button", { name: /현재 위치 사용/ }).click();
  await expect(page.getByRole("cell", { name: "0.42km" })).toBeVisible();
  expect(api.gets.some((path) => path.startsWith("/places/nearby?kind=hospital&lat=37.5&lon=127.03"))).toBe(true);

  await page.locator("label", { hasText: "장묘업체" }).click();
  await expect(page.getByText("좌표가 없어 현재 위치 검색은 지원하지 않고", { exact: false })).toBeVisible();
  await expect(page.getByLabel("시/군/구")).toHaveCount(0);
});

test("a place answer in the chat links to the place page", async ({ page }) => {
  await fakeApi(page, [[result("강남구 동물병원입니다.", { route: "sql", hospital_rows: [{ id: "hospital-1", name: "강남동물병원1", road_address: "서울특별시 강남구 테헤란로 1", latitude: 37.5, longitude: 127.03 }] })]], PLACES);
  await page.goto("/chat");
  await ask(page, "강남구 동물병원 알려줘");
  await page.getByRole("link", { name: "강남동물병원1" }).click();
  await expect(page.getByRole("heading", { name: "강남동물병원1" })).toBeVisible();
});

test("the menu leads between the pages", async ({ page }) => {
  await fakeApi(page, [], PLACES);
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toContainText("어떤 점이 걱정되세요?");
  await page.getByRole("link", { name: /^시설 찾기 동물병원/ }).click(); // a shortcut card
  await expect(page.getByRole("heading", { name: "반려동물 시설 찾기" })).toBeVisible();
  await page.getByRole("link", { name: "라그도그", exact: true }).click();
  await expect(page).toHaveURL(/\/$/);
  await openFromMenu(page, "찾기", "시설 찾기");
  await expect(page.getByRole("heading", { name: "반려동물 시설 찾기" })).toBeVisible();
  await expect(page.getByRole("navigation", { name: "찾기 메뉴" }).getByRole("link", { name: "시설 찾기" })).toHaveAttribute("aria-current", "page");
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBe(0);
});

test("the mouse wheel over the map zooms it", async ({ page, isMobile }) => {
  test.skip(isMobile, "no mouse wheel on a phone; pinch zoom is Leaflet's default");
  await fakeApi(page, [], PLACES);
  await page.goto("/places");
  await page.getByLabel("시/군/구").selectOption("강남구");
  await page.getByRole("button", { name: "조회" }).click();
  const map = page.getByRole("region", { name: "시설 지도" });
  await expect(map).toBeVisible();
  // Zooming in pulls the two markers apart on screen.
  const gap = () =>
    map.locator("path.leaflet-interactive").evaluateAll((paths) => {
      const [a, b] = paths.map((path) => path.getBoundingClientRect());
      return Math.hypot(a.x - b.x, a.y - b.y);
    });
  await expect(map.locator("path.leaflet-interactive")).toHaveCount(2);
  await map.scrollIntoViewIfNeeded(); // the mouse must be over the map, inside the window
  await page.waitForTimeout(800); // the fit-to-markers animation
  const before = await gap();
  const box = (await map.boundingBox())!;
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.wheel(0, -400);
  await expect.poll(gap).toBeGreaterThan(before * 1.5);
});
