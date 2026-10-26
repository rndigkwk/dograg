# 아키텍처 결정 기록 (ADR)

되돌리기 비싼 결정을 한 장씩 남긴다. 형식은 Nygard의 다섯 칸이다: 제목, 상태, 맥락, 결정, 결과. 결과 칸에는 **다시 검토할 조건**을 적는다.

- 2026-10-13에 소급해 썼다. 결정은 그 전에 내렸고, 근거 수치는 당시 기록에서 옮겼다. 원래 기록은 [improvement-log.md](../improvement-log.md), [design.md](../design.md)(지금은 [architecture/](../architecture/README.md)), [wiki/](../wiki/)에 있다.
- 채택한 ADR은 고치지 않는다. 결정이 바뀌면 새 ADR을 쓰고, 옛 ADR의 상태를 "대체됨"으로 바꾼다.
- 작은 기본 설정은 관련 ADR에 한 줄로만 남긴다. 예: 검색기마다 후보 12건, 근거 평가 후보 5건.

| 번호 | 결정 | 상태 |
| --- | --- | --- |
| [0001](0001-embedding-finetuned-ko-sroberta.md) | 건강 상담 임베딩으로 보호자 말투로 미세조정한 ko-sroberta 사용(질문은 ONNX int8), 보고서는 OpenAI 임베딩 | 채택 |
| [0002](0002-hybrid-dense-bm25-rrf.md) | 검색 전략으로 Dense + BM25(Kiwi) 하이브리드, RRF 합치기 사용 | 채택 |
| [0003](0003-vector-store-faiss-flat.md) | 벡터 저장소로 메모리 안 전수 검색 사용(건강·보고서 모두). 외부 DB 허용 뒤 서울 pgvector와 다시 비교해도 1위 | 대체됨 (0007) |
| [0004](0004-no-shared-db.md) | 두 배포에 공유 DB를 두지 않음 (Claude 권고였고 소유자 결정이 아니어서 거절, 외부 DB 허용) | 거절 |
| [0005](0005-no-reranker.md) | 리랭커를 쓰지 않음 | 채택 |
| [0006](0006-cloud-run-region-seoul.md) | Cloud Run 지역은 서울 유지 (us-central1과 한국에서 비교: 답변 완료 8.6 대 9.4초) | 채택 |
| [0007](0007-search-in-supabase.md) | 벡터·키워드 검색을 Supabase(pgvector + PGroonga)로. 앱 최고 메모리 910 → 442MB, 검색 품질 같음. 장애 시 로컬 검색, float16 저장. Streamlit Cloud 최고 702MB. **덧붙임:** 키워드 쪽은 운영 측정으로 PGroonga에서 뺐다(보고서는 메모리 BM25 #211, 건강은 의미 검색만 #218) | 채택 (키워드 부분 변경) |
| [0008](0008-nextjs-frontend-fastapi-backend.md) | 화면은 Next.js(Vercel), 앱 로직은 FastAPI(Cloud Run)로 나누고 로그인은 Supabase Auth + RLS. 단계 P1 API → P2 질병 문의 → P3 나머지 화면 → P4 로그인 → P5 전환 | 채택 (P5 남음) |
| [0009](0009-consultation-memory.md) | 지난 상담 기억은 보호자가 고른 "상담 노트"(300자, 최대 30개)를 사용자 계정 테이블(RLS)에 두고, 새 질문에 브라우저가 최근 5개를 보냄. 기본 꺼짐, 보기·지우기 화면 | 채택 |
| [0010](0010-public-care-guides.md) | 일상 관리 질문은 공공기관 돌봄 지침 5종으로 보강하고, 상담 컬렉션과 따로 메모리에 색인. 공공누리 없는 자료는 비공개 보관·짧은 인용·출처 링크 | 채택 |
| [0011](0011-degrade-on-model-quota.md) | 모델 사용 한도가 떨어지면 검색 결과(상담·지침)와 안내로 버티고, 평가·CI와 운영의 OpenAI 키를 나누고, 데이터 변경도 병합 게이트에 | 채택 (키 분리는 소유자 작업 남음) |
| [0012](0012-claude-fallback.md) | OpenAI가 한도·시간 초과·연결 실패·5xx로 응답하지 못하면 상담 경로(근거 평가, 채팅, 건강 답변)의 같은 호출을 Claude Haiku 5.5가 대신 받음. 둘 다 실패하면 0011의 낮춘 화면. 방문 준비 팀은 제외 | 채택 |
