# 아키텍처 결정 기록 (ADR)

되돌리기 비싼 결정을 한 장씩 남긴다. 형식은 Nygard의 다섯 칸이다: 제목, 상태, 맥락, 결정, 결과. 결과 칸에는 **다시 검토할 조건**을 적는다.

- 2026-10-13에 소급해 썼다. 결정은 그 전에 내렸고, 근거 수치는 당시 기록에서 옮겼다. 원래 기록은 [improvement-log.md](../improvement-log.md), [design.md](../design.md), [wiki/](../wiki/)에 있다.
- 채택한 ADR은 고치지 않는다. 결정이 바뀌면 새 ADR을 쓰고, 옛 ADR의 상태를 "대체됨"으로 바꾼다.
- 작은 기본 설정은 관련 ADR에 한 줄로만 남긴다. 예: 검색기마다 후보 12건, 근거 평가 후보 5건.

| 번호 | 결정 | 상태 |
| --- | --- | --- |
| [0001](0001-embedding-finetuned-ko-sroberta.md) | 건강 상담 임베딩으로 보호자 말투로 미세조정한 ko-sroberta 사용(질문은 ONNX int8), 보고서는 OpenAI 임베딩 | 채택 |
| [0002](0002-hybrid-dense-bm25-rrf.md) | 검색 전략으로 Dense + BM25(Kiwi) 하이브리드, RRF 합치기 사용 | 채택 |
| [0003](0003-vector-store-faiss-flat.md) | 벡터 저장소로 메모리 안 전수 검색 사용(건강·보고서 모두). 외부 DB 허용 뒤 서울 pgvector와 다시 비교해도 1위 | 채택 (전환은 다음 PR) |
| [0004](0004-no-shared-db.md) | 두 배포에 공유 DB를 두지 않음 (Claude 권고였고 소유자 결정이 아니어서 거절, 외부 DB 허용) | 거절 |
| [0005](0005-no-reranker.md) | 리랭커를 쓰지 않음 | 채택 |
| [0006](0006-cloud-run-region-seoul.md) | Cloud Run 지역은 서울 유지 (us-central1과 한국에서 비교: 답변 완료 8.6 대 9.4초) | 채택 |
| [0007](0007-search-in-supabase.md) | 벡터·키워드 검색을 Supabase(pgvector + PGroonga)로. 앱 최고 메모리 910 → 442MB, 검색 품질 같음 | 제안 |
