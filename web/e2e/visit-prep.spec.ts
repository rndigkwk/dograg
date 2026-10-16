import { expect, test } from "@playwright/test";

import { ask, fakeApi, result } from "./fake-api";

const REPORT = { report: "# 방문 준비 보고서\n\n- 설사가 이틀째입니다.", passed: true, status: "검수 통과", round: 1, steps: [], urgent: false, seconds: 42, answered: true };

test("a report pauses for the guardian's answer, then comes back reviewed", async ({ page }) => {
  const api = await fakeApi(page, [], {}, {
    "/visit-prep": [
      ["step", { line: "검색 자료를 준비했습니다" }],
      ["step", { line: "증상 조사를 마쳤습니다" }],
      ["paused", { thread_id: "t1", questions: ["언제부터였나요?", "밥은 먹나요?"] }],
    ],
    "/visit-prep/t1/answer": [["step", { line: "보고서를 검수했습니다" }], ["result", REPORT]],
  });
  await page.goto("/visit-prep");
  await page.getByLabel("상담 내용").fill("말티즈가 이틀째 설사를 해요");
  await page.getByLabel("근처 동물병원을 찾을 지역 (선택)").fill("강남구");
  await page.getByRole("button", { name: /방문 준비 보고서 만들기/ }).click();

  const questions = page.getByRole("region", { name: "보호자 질문" });
  await expect(questions.getByRole("listitem")).toHaveText(["언제부터였나요?", "밥은 먹나요?"]);
  await questions.getByLabel(/답변/).fill("어제 저녁부터요");
  await questions.getByRole("button", { name: "답하고 보고서 만들기" }).click();

  await expect(page.getByRole("status").filter({ hasText: "검수 통과" })).toHaveText("검수 통과 · 다시 쓰기 1회 · 42초 · 보호자 답변 반영");
  await expect(page.getByRole("heading", { name: "방문 준비 보고서", exact: true })).toBeVisible();
  await expect(page.getByRole("region", { name: "진행 과정" })).toContainText("✓ 보고서를 검수했습니다");
  await expect(questions).toHaveCount(0);
  expect(api.posts[0].body).toEqual({ consultation: "말티즈가 이틀째 설사를 해요", region: "강남구", profile: "" });
  expect(api.posts[1].body).toEqual({ answer: "어제 저녁부터요" });

  // Word and plain text for anyone; Markdown for those who use it.
  for (const [button, file] of [[/Word/, "방문준비보고서.docx"], [/텍스트/, "방문준비보고서.txt"], [/Markdown/, "방문준비보고서.md"]] as const) {
    const download = page.waitForEvent("download");
    await page.getByRole("button", { name: button }).click();
    const saved = await download;
    expect(saved.suggestedFilename()).toBe(file);
    const bytes = await (await saved.createReadStream()).toArray().then((chunks) => Buffer.concat(chunks));
    if (file.endsWith(".docx")) expect(bytes.subarray(0, 2).toString()).toBe("PK");
    if (file.endsWith(".txt")) expect(bytes.toString("utf8")).toContain("• 설사가 이틀째입니다.");
  }
});

test("an urgent consultation warns first; a busy server and an expired pause say so", async ({ page }) => {
  await fakeApi(page, [], {}, {
    "/visit-prep": [["urgent", { notice: "응급" }], ["paused", { thread_id: "old", questions: ["언제부터였나요?"] }]],
    "/visit-prep/old/answer": 404,
  });
  await page.goto("/visit-prep");
  await page.getByLabel("상담 내용").fill("강아지가 경련을 하고 쓰러졌어요");
  await page.getByRole("button", { name: /방문 준비 보고서 만들기/ }).click();
  await expect(page.getByRole("alert").filter({ hasText: "응급 징후가 의심됩니다" })).toBeVisible();
  await page.getByRole("button", { name: "건너뛰고 바로 만들기" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "30분이 지나" })).toBeVisible();
});

test("the report limit and a busy team are shown as they come", async ({ page }) => {
  await fakeApi(page, [], {}, { "/visit-prep": [["busy", { message: "다른 사용자의 보고서를 만드는 중입니다. 1~2분 뒤에 다시 시도해 주세요." }]] });
  await page.goto("/visit-prep");
  await page.getByLabel("상담 내용").fill("설사를 해요");
  await page.getByRole("button", { name: /방문 준비 보고서 만들기/ }).click();
  await expect(page.getByRole("status").filter({ hasText: "다른 사용자의 보고서를 만드는 중입니다" })).toBeVisible();
});

test("a health answer carries its question to the report page, not in the URL", async ({ page }) => {
  await fakeApi(page, [[result("수분을 챙겨 주세요.")]]);
  await page.goto("/chat");
  await ask(page, "말티즈가 이틀째 설사를 해요");
  await page.getByRole("button", { name: /이 상담으로 방문 준비 보고서 만들기/ }).click();
  await expect(page).toHaveURL(/\/visit-prep$/);
  await expect(page.getByLabel("상담 내용")).toHaveValue("말티즈가 이틀째 설사를 해요");
});

test("the current location fills the district and goes with the report request", async ({ page, context }) => {
  await context.grantPermissions(["geolocation"]);
  await context.setGeolocation({ latitude: 37.4939633, longitude: 127.0448504 });
  const api = await fakeApi(
    page,
    [],
    { "/places/nearby": { places: [{ id: "hospital-1", kind: "hospital", name: "온숲", address: "서울특별시 강남구 도곡로 241", latitude: 37.4939633, longitude: 127.0448504, info: {}, info_lines: [], phone: null, homepage: null, category: null, distance_km: 0 }] } },
    { "/visit-prep": [["result", REPORT]] },
  );
  await page.goto("/visit-prep");
  await page.getByLabel("상담 내용").fill("설사를 해요");
  await page.getByRole("button", { name: /현재 위치 사용/ }).click();
  await expect(page.getByLabel("근처 동물병원을 찾을 지역 (선택)")).toHaveValue("서울특별시 강남구");
  await expect(page.getByText("직선거리 순으로 찾습니다", { exact: false })).toBeVisible();
  await page.getByRole("button", { name: /방문 준비 보고서 만들기/ }).click();
  await expect(page.getByRole("status").filter({ hasText: "검수 통과" })).toBeVisible();
  expect(api.posts[0].body).toEqual({ consultation: "설사를 해요", region: "서울특별시 강남구", profile: "", location: [37.4939633, 127.0448504] });
});

test("typing a region by hand drops the location", async ({ page, context }) => {
  await context.grantPermissions(["geolocation"]);
  await context.setGeolocation({ latitude: 37.5, longitude: 127.03 });
  const api = await fakeApi(page, [], { "/places/nearby": { places: [] } }, { "/visit-prep": [["result", REPORT]] });
  await page.goto("/visit-prep");
  await page.getByLabel("상담 내용").fill("설사를 해요");
  await page.getByRole("button", { name: /현재 위치 사용/ }).click();
  await expect(page.getByText("직선거리 순으로 찾습니다", { exact: false })).toBeVisible();
  await page.getByLabel("근처 동물병원을 찾을 지역 (선택)").fill("마포구");
  await page.getByRole("button", { name: /방문 준비 보고서 만들기/ }).click();
  await expect(page.getByRole("status").filter({ hasText: "검수 통과" })).toBeVisible();
  expect(api.posts[0].body).toEqual({ consultation: "설사를 해요", region: "마포구", profile: "" });
});
