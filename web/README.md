# RagDog 웹 화면 (Next.js)

Streamlit 화면을 옮기는 새 화면입니다(docs/adr/0008). 답변 로직은 없고, 배포된 API(`api/`, Cloud Run `ragdog-api`)를 부릅니다.

```bash
cd web
npm ci
npm run dev        # http://localhost:3000
npm test           # 스트림 해석·대화 상태 단위 테스트
```

- **API 주소:** `NEXT_PUBLIC_RAGDOG_API_URL`. 없으면 배포된 `ragdog-api`를 씁니다.
- **CORS:** API는 `http://localhost:3000`과 `RAGDOG_WEB_ORIGINS`·`RAGDOG_WEB_ORIGIN_REGEX`(저장소 변수)에 적힌 주소만 받습니다.
- **질문 한도:** 질문은 한도에 들어갑니다. 브라우저당 시간당 10번, 하루 30번이고, 질문마다 모델을 부릅니다.
