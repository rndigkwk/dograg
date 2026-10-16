import { expect, type Page, test } from "@playwright/test";

import { ask, fakeApi, result } from "./fake-api";

const conversation = (page: Page) => page.getByLabel("대화", { exact: true });

/** The conversation list: always shown on wide screens, behind a button on phones. */
async function openList(page: Page) {
  const toggle = page.getByRole("button", { name: /^대화 기록/ });
  if ((await toggle.isVisible()) && (await toggle.getAttribute("aria-expanded")) !== "true") await toggle.click();
}

test("a question streams into an answer with evidence and feedback", async ({ page }) => {
  const api = await fakeApi(page, [
    [
      ["step", { message: "건강 상담 자료에서 근거를 찾고 있습니다" }],
      ["token", { text: "설사가 이틀 넘게 " }],
      ["token", { text: "계속되면 병원에 가세요." }],
      result("설사가 이틀 넘게 계속되면 병원에 가세요. 체중 5~10% 감소도 확인하세요.", {
        evidence_rows: [{ "meta.lifeCycle": "성견", "meta.department": "내과", "meta.disease": "장염", "qa.output": "수액 치료를 합니다." }],
      }),
    ],
  ]);
  await page.goto("/");
  await ask(page, "말티즈가 이틀째 설사를 해요");

  await expect(conversation(page).getByText("설사가 이틀 넘게 계속되면 병원에 가세요.", { exact: false })).toBeVisible();
  await expect(page.getByText("5~10%", { exact: false })).toBeVisible(); // a range, not strikethrough
  await page.getByText("1. 성견 / 내과 / 장염").click();
  await expect(page.getByText("수액 치료를 합니다.")).toBeVisible();

  await page.getByRole("button", { name: "아쉬워요" }).click();
  await page.getByLabel("근거가 부족해요").check();
  await page.getByLabel(/이 질문과 답변을 개선에 쓰도록 보내기/).check();
  await page.getByRole("button", { name: "보내기", exact: true }).first().click();
  await expect(page.getByText("보내 주셔서 고맙습니다.", { exact: false })).toBeVisible();

  expect(api.chats[0]).toMatchObject({ question: "말티즈가 이틀째 설사를 해요", history: [], profile: null, suggest_memory: true });
  expect(api.feedback.map((call) => call.path)).toEqual(["/feedback", "/feedback/reason", "/feedback/review"]);
  expect(api.feedback[2].body).toMatchObject({ question: "말티즈가 이틀째 설사를 해요", reason: "근거가 부족해요", route: "rag" });
});

test("an urgent warning comes before the answer, with the nearest hospitals", async ({ page, context }) => {
  await context.grantPermissions(["geolocation"]);
  await context.setGeolocation({ latitude: 37.5, longitude: 127.03 });
  const api = await fakeApi(page, [
    [
      [
        "urgent",
        {
          notice: "응급 징후가 의심됩니다. 지체하지 말고 가까운 동물병원에 연락하세요.",
          hospitals: { nearest: [{ name: "강남24시동물병원", distance_km: 1.24, phone: "02-123-4567", road_address: "서울 강남구 테헤란로 1" }], night: [] },
        },
      ],
      result("바로 병원에 가세요.", { safety_notice: "응급 징후가 의심됩니다." }),
    ],
  ]);
  await page.goto("/");
  await page.getByRole("button", { name: /현재 위치 사용/ }).click();
  await expect(page.getByText("현재 위치를 사용합니다.", { exact: false })).toBeVisible();
  await ask(page, "강아지가 경련을 하고 쓰러졌어요");

  const alert = page.getByRole("alert").filter({ hasText: "가까운 동물병원" }); // not Next.js's route announcer
  await expect(alert).toContainText("응급 징후가 의심됩니다");
  await expect(alert.getByRole("link", { name: "02-123-4567" })).toHaveAttribute("href", "tel:021234567");
  await expect(alert).toContainText("1.2km");
  await expect(page.getByRole("note")).toHaveCount(1); // the storage notice only: the repeated warning is dropped
  expect(api.chats[0].location).toEqual([37.5, 127.03]);
});

test("the question limit shows a notice that is neither stored nor sent back", async ({ page }) => {
  const api = await fakeApi(page, [
    [["limited", { message: "질문 한도를 넘었습니다. 40분 뒤에 다시 질문해 주세요.", wait_minutes: 40 }]],
    [result("두 번째 답")],
  ]);
  await page.goto("/");
  await ask(page, "첫 질문");
  await expect(page.getByRole("status").filter({ hasText: "질문 한도를 넘었습니다" })).toBeVisible();
  await ask(page, "두 번째 질문");
  await expect(conversation(page).getByText("두 번째 답")).toBeVisible();
  expect(api.chats[1].history).toEqual([]);
  await openList(page);
  await expect(page.getByRole("button", { name: "두 번째 질문" })).toBeVisible();
  await expect(page.getByRole("button", { name: "첫 질문" })).toHaveCount(0);
});

test("conversations stay in the browser and can be continued, started and deleted", async ({ page }) => {
  const api = await fakeApi(page, [[result("첫 답")], [result("이어진 답")], [result("새 답")]]);
  await page.goto("/");
  await ask(page, "강아지가 구토해요");
  await expect(conversation(page).getByText("첫 답")).toBeVisible();

  await page.reload();
  await expect(page.getByRole("note")).toHaveCount(0); // the storage notice shows once per browser
  await openList(page);
  await page.getByRole("button", { name: "강아지가 구토해요" }).click();
  await expect(conversation(page).getByText("첫 답")).toBeVisible();
  await ask(page, "계속 토하면요?");
  await expect(conversation(page).getByText("이어진 답")).toBeVisible();
  expect(api.chats[1].history).toEqual([
    { role: "user", content: "강아지가 구토해요" },
    { role: "assistant", content: "첫 답", route: "rag" },
  ]);

  await openList(page);
  await page.getByRole("button", { name: "+ 새 대화" }).click();
  await ask(page, "다른 질문");
  await expect(conversation(page).getByText("새 답")).toBeVisible();
  expect(api.chats[2].history).toEqual([]);

  await openList(page);
  await page.getByRole("button", { name: "이 대화 삭제" }).click();
  await openList(page);
  await expect(page.getByRole("button", { name: "다른 질문" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "강아지가 구토해요" })).toBeVisible();
});

test("a memory suggestion is saved only on click and sent with the next question", async ({ page }) => {
  const api = await fakeApi(page, [
    [result("답"), ["memory", { profile: { name: "두부", breed: "말티즈", birth_month: "2023-04-01" }, new_facts: [], summary: "이름 두부", update: false }]],
    [result("답2"), ["memory", { profile: { name: "두부", breed: "말티즈", birth_month: "2023-04-01", medications: ["심장약"] }, new_facts: ["복용약: 심장약"], summary: "복용약: 심장약", update: true }]],
    [result("답3")],
  ]);
  await page.goto("/");
  await ask(page, "두부는 3살 말티즈예요. 구토를 해요");
  const card = page.getByRole("region", { name: "기억 제안" });
  await expect(card).toContainText("이름: 두부 · 견종: 말티즈");
  await card.getByRole("button", { name: "우리 아이 정보에 저장" }).click();
  await expect(card).toHaveCount(0);

  await ask(page, "두부가 심장약을 먹어요");
  await expect(card).toContainText("새로 알게 된 정보를 기억할까요? 복용약: 심장약");
  await card.getByRole("button", { name: "기억하지 않기" }).click();
  await ask(page, "또 질문");
  await expect(conversation(page).getByText("답3")).toBeVisible();

  expect(api.chats[1].profile).toEqual({ name: "두부", breed: "말티즈", birth_month: "2023-04-01" });
  expect(api.chats[2].declined_memory).toEqual(["복용약: 심장약"]);
  await openList(page);
  await page.getByText("🐾 우리 아이 정보").filter({ visible: true }).click();
  await expect(page.getByText(/이름: 두부 · 견종: 말티즈 · 나이: 약 \d+살/).filter({ visible: true })).toBeVisible();
});

test("the page fits a phone screen", async ({ page }) => {
  await fakeApi(page, [[result("답")]]);
  await page.goto("/");
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBe(0);
});
