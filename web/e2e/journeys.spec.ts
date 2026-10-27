import { expect, type Page, test } from "@playwright/test";

import { ask, fakeApi, result } from "./fake-api";

// User journeys across pages (2026-10-27): each page has its own tests, these check that what the
// guardian did on one page is still there on the next. No model: the API is faked. A journey fails
// on the first fact that did not carry over.

const conversation = (page: Page) => page.getByLabel("대화", { exact: true });

const REPORT = { report: "# 방문 준비 보고서\n\n- 설사가 이틀째입니다.", passed: true, status: "검수 통과", round: 1, steps: [], urgent: false, seconds: 42, answered: true };

test("care schedule → home question → two chat turns → citation → visit report with every fact", async ({ page }) => {
  await page.clock.setFixedTime(new Date("2026-10-27T10:00:00"));
  const api = await fakeApi(
    page,
    [
      [result("이틀 넘게 설사하면 병원에 가세요. [사례 1]", {
        evidence_rows: [{ "meta.lifeCycle": "성견", "meta.department": "내과", "meta.disease": "장염", question: "강아지가 이틀째 설사를 해요", "qa.output": "수액 치료를 합니다." }],
      })],
      [result("구토가 없으면 탈수부터 살피세요.")],
    ],
    {},
    { "/visit-prep": [["result", REPORT]] },
  );

  // 1. The care schedule: the last rabies shot was over a year ago.
  await page.goto("/care");
  await page.getByLabel("광견병 추가접종 마지막으로 한 날").fill("2025-09-01");

  // 2. A question from the home page, then a follow-up in the chat.
  await page.goto("/");
  await page.getByRole("textbox", { name: "질문" }).fill("강아지가 어제부터 설사를 해요");
  await page.getByRole("button", { name: "질문하기" }).click();
  await expect(conversation(page).getByText("이틀 넘게 설사하면 병원에 가세요.")).toBeVisible();
  await ask(page, "5살이고 7kg입니다. 구토는 없어요");
  await expect(conversation(page).getByText("구토가 없으면 탈수부터 살피세요.")).toBeVisible();

  // 3. The citation in the first answer opens its consultation.
  const card = page.locator("details", { hasText: "사례 1 · 강아지가 이틀째 설사를 해요" });
  await conversation(page).getByRole("link", { name: "사례 1" }).click();
  await expect(card).toHaveAttribute("open");

  // 4. The report gets both questions and the overdue shot, and nothing from the model's answers.
  await page.getByRole("button", { name: "이 상담으로 방문 준비 보고서 만들기" }).last().click();
  await expect(page).toHaveURL(/\/visit-prep$/);
  await expect(page.getByLabel("상담 내용")).toHaveValue("강아지가 어제부터 설사를 해요\n5살이고 7kg입니다. 구토는 없어요");
  await expect(page.getByText(/관리 일정에서 지금 할 때이거나 기한이 지난 항목 넣기: 광견병 추가접종/)).toBeVisible();
  await page.getByRole("button", { name: /방문 준비 보고서 만들기/ }).click();
  await expect(page.getByRole("status").filter({ hasText: "검수 통과" })).toBeVisible();

  const sent = api.posts[0].body;
  const facts = ["어제부터 설사", "5살", "7kg", "구토는 없어요"];
  expect(facts.filter((fact) => !String(sent.consultation).includes(fact))).toEqual([]);
  expect(String(sent.consultation)).not.toContain("병원에 가세요"); // the model's words stay out
  expect(sent.care).toEqual({ rabies: "2025-09-01" });
  expect(api.chats.map((chat) => chat.question)).toEqual(["강아지가 어제부터 설사를 해요", "5살이고 7kg입니다. 구토는 없어요"]);
});

const hospital = {
  id: "hospital-1",
  kind: "hospital",
  name: "강남동물병원1",
  address: "서울특별시 강남구 테헤란로 1",
  road_address: "서울특별시 강남구 테헤란로 1",
  phone: "02-123-4567",
  homepage: null,
  category: null,
  latitude: 37.5,
  longitude: 127.03,
  info: {},
  info_lines: [],
};
const source = { title: "행정안전부 동물병원 인허가 정보", url: "https://www.data.go.kr", rows: 5459, updated: "2026-08-11 22:02:01" };
const fee = (median: number) => ({ mean: median, median, min: median / 2, max: median * 2 });
const LOOKUPS = {
  "/places/kinds": [{ kind: "hospital", label: "동물병원", has_location: true, source }],
  "/places/regions": { 서울특별시: ["강남구", "서초구"] },
  "/places/search": { total: 1, places: [hospital] },
  "/places/hospital-1": hospital,
  "/fees/region": {
    province: "서울특별시",
    city: "강남구",
    basis: "강남구",
    items: [{ item: "초진 진찰료", detail: "체중 5kg", label: "초진 진찰료 (체중 5kg)", national_median: 10000, median: 11000, level: "sigungu", region: "강남구" }],
    source: "농림축산식품부 동물병원 진료비 현황 조사(2025, animalclinicfee.or.kr)",
    notice: "지역별 조사 통계이며 개별 병원의 가격이 아닙니다.",
  },
  "/fees/items": { items: [{ category: "진찰료", item: "초진 진찰료", detail: "체중 5kg", label: "초진 진찰료 (체중 5kg)" }], source: "", notice: "" },
  "/fees": {
    item: "초진 진찰료",
    detail: "체중 5kg",
    category: "진찰료",
    label: "초진 진찰료 (체중 5kg)",
    national: fee(10000),
    sido: [{ sido: "서울특별시", ...fee(10000) }],
    sigungu: [{ sido: "서울특별시", sigungu: "강남구", ...fee(11000) }],
    no_data: [],
    collected: "2026-10-10",
    source: "농림축산식품부 동물병원 진료비 현황 조사(2025, animalclinicfee.or.kr)",
    source_url: "https://animalclinicfee.or.kr/info/payInfo.do",
    notice: "",
  },
};

test("chat place answer → place page and directions → the district's fees → the fee map of that district", async ({ page }) => {
  await fakeApi(page, [[result("강남구 동물병원입니다.", { route: "sql", hospital_rows: [hospital] })]], LOOKUPS);

  // 1. A place answer links to the place.
  await page.goto("/chat");
  await ask(page, "강남구 동물병원 알려줘");
  await conversation(page).getByRole("link", { name: "강남동물병원1" }).click();
  await expect(page).toHaveURL(/\/places\?id=hospital-1$/);
  await expect(page.getByRole("heading", { name: "강남동물병원1" })).toBeVisible();

  // 2. Directions go to Kakao Map with the place's name and position.
  const directions = page.getByRole("link", { name: /카카오맵에서 길찾기/ });
  await expect(directions).toHaveAttribute("href", /map\.kakao\.com\/link\/to\/.*37\.5,127\.03/);

  // 3. Searching its district shows the district's fees next to the nation's.
  await page.getByRole("link", { name: "← 다른 장소 찾기" }).click();
  await page.getByLabel("시/군/구").selectOption("강남구");
  await page.getByRole("button", { name: "조회" }).click();
  await expect(page.getByText(/초진 진찰료 \(체중 5kg\).*중간 11,000원 · 전국보다 1,000원 높음/)).toBeVisible();

  // 4. The fee page's map reaches the same district and the same figure.
  await page.getByRole("link", { name: "지역별 진료비" }).last().click();
  await expect(page).toHaveURL(/\/fees$/);
  const map = page.getByRole("group", { name: "지도" });
  await map.getByRole("button", { name: "서울특별시 중간값 10,000원" }).click();
  await map.getByRole("button", { name: "강남구 중간값 11,000원" }).click();
  await expect(page.getByRole("region", { name: "서울특별시 강남구 · 초진 진찰료 (체중 5kg) 진료비" })).toContainText("11,000원");
});
