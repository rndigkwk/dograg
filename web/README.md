# RagDog 웹 화면 (Next.js)

Streamlit 화면을 옮기는 새 화면입니다(docs/adr/0008). 답변 로직은 없고, 배포된 API(`api/`, Cloud Run `ragdog-api`)를 부릅니다.

```bash
cd web
npm ci
npm run dev        # http://localhost:3000
npm test           # 스트림 해석·대화 상태 단위 테스트
npm run e2e        # 화면 흐름 (Playwright, API는 가짜로 바꿈: 모델 호출 0)
```

- **API 주소:** `NEXT_PUBLIC_RAGDOG_API_URL`. 없으면 배포된 `ragdog-api`를 씁니다.
- **CORS:** API는 `RAGDOG_WEB_ORIGINS`·`RAGDOG_WEB_ORIGIN_REGEX`(저장소 변수)에 적힌 주소만 받습니다. 바꾼 뒤에는 API를 다시 배포해야 반영됩니다.
  - 지금 값: 정식 주소 `https://ragdog-rndigkwks-projects.vercel.app`와 `http://localhost:3000`, 미리보기 `^https://ragdog-[a-z0-9-]+-rndigkwks-projects\.vercel\.app$`
  - `RAGDOG_WEB_ORIGINS`를 정하면 기본값 `http://localhost:3000`을 대신합니다. 로컬 개발을 위해 localhost도 함께 적어 둡니다(2026-10-16, 빠뜨려 로컬 화면이 막혔음).
- **화면:** `/chat` 질병 문의, `/places` 시설 찾기(`?id=`로 한 곳). 지도는 OpenStreetMap 타일(Leaflet)입니다.
- **질문 한도:** 질문은 한도에 들어갑니다. 브라우저당 시간당 10번, 하루 30번이고, 질문마다 모델을 부릅니다.
