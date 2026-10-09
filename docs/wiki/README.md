# RagDog 프로젝트 위키

코드만 봐서는 알 수 없는 **결정의 이유, 실험 수치, 하지 않기로 한 것**을 모아 둔 곳입니다.
기능 소개와 실행 방법은 루트 [README.md](../../README.md)를 보세요. 코드 동작 설명은 여기에 쓰지 않습니다(코드와 금방 어긋나기 때문).

## 페이지

| 페이지 | 내용 |
| --- | --- |
| [data.md](data.md) | 데이터 출처, 규모, 품질 감사 결과, 라벨 문제 |
| [places-data.md](places-data.md) | 반려동물 시설 DB: 공공데이터 6종 정제, 출처 간 중복 판단, 종류 판별 규칙 |
| [retrieval-experiments.md](retrieval-experiments.md) | 건강 RAG 검색 실험: Dense → 재정렬(기각) → Dense+BM25 RRF(채택), 답변 유사도 평가 |
| [embedding-finetune.md](embedding-finetune.md) | 건강 검색 임베딩 미세조정: 합성 질의 생성, Colab T4 학습, 짧은 질문 `useful@3` 0.625 → 0.800 |
| [router.md](router.md) | 질문 라우터 구조와 Jev 섀도 비교 결과 |
| [safety-and-evidence.md](safety-and-evidence.md) | 응급 신호, 근거 부족 처리, 위치 개인정보, 보고서 근거 표시에 관한 결정 |
| [open-questions.md](open-questions.md) | 미해결 과제와 알려진 불일치 |
| [observability.md](observability.md) | Langfuse 트레이싱: 남기는 값, 텍스트 마스킹과 검증, 운영 설정(태그·release), 실험·정기 회귀 평가 |
| [visit-prep-team.md](visit-prep-team.md) | 멀티에이전트 방문 준비 보고서 팀: 상담 12개 실험(기준선 → 개선), 실패 처리와 장애 주입, 배포 장애 기록 |
| [deployment-resources.md](deployment-resources.md) | Streamlit Cloud 메모리 한도(2.7GB) 대비 구성 요소별 측정과 리랭커 비용 |
| [lecture-review.md](lecture-review.md) | Day 46~56 교안 기법별 적용·테스트·미적용 정리 (어떻게, 결과, 이유) |

## 작성 규칙

- **수치는 본문에 직접 적는다.** `output/`은 `.gitignore` 대상이라 팀원 저장소에는 JSON이 없다. 출처 파일명과 측정 날짜를 함께 남긴다.
- **결정에는 이유를 붙인다.** "무엇을 했다"보다 "왜 그렇게 했고, 무엇을 버렸는가"가 핵심이다.
- **함수 설명은 쓰지 않는다.** 필요하면 `파일:줄` 대신 파일 경로와 함수 이름만 언급한다(줄 번호는 금방 바뀜).
- 새 실험을 하면 해당 페이지에 날짜와 함께 항목을 추가하고, 결론이 바뀌면 예전 결론은 지우지 말고 "대체됨"으로 표시한다.

## 원천 자료

- 설계 문서: [docs/superpowers/specs/](../superpowers/specs/), [docs/superpowers/plans/](../superpowers/plans/)
- 답변 유사도 평가: [notebooks/docs/rag_answer_similarity_evaluation.md](../../notebooks/docs/rag_answer_similarity_evaluation.md), `notebooks/outputs/*.csv`
- 재생성 가능한 실험 결과(로컬 전용): `output/*.json` — 각 페이지에 생성 명령을 적어 둠
