# 기능별 설계와 이유 (옮김)

이 문서의 내용은 2026-10-26에 [`docs/architecture/`](architecture/README.md)로 옮겼습니다. 구성 요소마다 부품별 기능·처리 흐름·선택한 이유를 지금 코드 기준으로 다시 썼습니다. 예전 판(Streamlit 시절, 메모리 안 Kiwi BM25 검색)은 Git 기록에 있습니다.

| 예전 절 | 지금 있는 곳 |
| --- | --- |
| 0. 전체 구조 | [architecture/README.md](architecture/README.md) |
| 1. 질문 분류 (라우터) | [answer-pipeline.md](architecture/answer-pipeline.md) 1절 |
| 2. 건강 상담: 검색 | [retrieval.md](architecture/retrieval.md) |
| 2. 건강 상담: 근거 평가와 보류, 답변 | [answer-pipeline.md](architecture/answer-pipeline.md) 3~4절 |
| 3. 응급 신호 감지 | [answer-pipeline.md](architecture/answer-pipeline.md) 5절 |
| 4. 시설 찾기, 5. 지역별 진료비, 6. 보고서 분석 | [answer-pipeline.md](architecture/answer-pipeline.md) 6절, [retrieval.md](architecture/retrieval.md) 4절 |
| 7. 대화 기억과 개인정보 | [answer-pipeline.md](architecture/answer-pipeline.md) 7절, [frontend.md](architecture/frontend.md) 2절 |
| 8. 방문 준비 보고서 | [visit-prep-team.md](architecture/visit-prep-team.md) |
| 9. 관측과 평가, 10. 배포 | [operations.md](architecture/operations.md), [api.md](architecture/api.md) |
| 11. 데이터 | [data.md](architecture/data.md) |
