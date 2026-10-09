# 미해결 과제와 알려진 불일치

해결하면 항목을 지우지 말고 ~~취소선~~과 날짜, 커밋을 남기세요.

## 문서와 코드가 다른 부분

- ~~루트 README의 건강 RAG 설명이 하이브리드 검색 이전 상태다.~~ 2026-10-02 갱신: 하이브리드 검색 설명, 비교 표, `scripts/`·`docs/wiki/` 구조를 반영함.
- README의 답변 유사도(0.7448 / 0.7721)는 아직 Dense 검색 시점 수치다. 하이브리드 검색 기준으로 다시 측정하지 않았다.

## 데이터

- `무릎뼈 탈구` / `무릎뼈탈구`, `치과` / ` 치과` 표기 불일치가 Chroma 메타데이터와 필터에 그대로 남아 있다([data.md](data.md)).
- 검증 데이터에 `기타` 라벨이 없어서, 학습 데이터의 76.9%를 차지하는 `기타` 문서의 검색 품질을 평가할 수 없다.
- ~~좌표가 없거나 잘못된 병원이 몇 곳인지 집계하지 않았다.~~ → 2026-10-07 집계: 영업 중인 병원 5,459곳 중 216곳은 좌표가 없거나 국내 범위 밖이다([places-data.md](places-data.md)).

## 검색·생성

- 검색 근거보다 생성 답변의 유사도가 낮다(0.7721 → 0.7448). 원인은 분석하지 않았다.
- 관련도 임계값이 없어서, 범위 밖 질문에도 근거 k건이 붙는다([safety-and-evidence.md](safety-and-evidence.md)).
- ~~BM25 색인 구축이 앱 콜드 스타트를 수 분 늦춘다.~~ 2026-10-05 토큰 캐시와 백그라운드 워밍업으로 해결. 로컬 첫 질문 165초 이상 → 8초([deployment-resources.md](deployment-resources.md)).
- RRF 동점(검증 질문의 79%에서 상위 4건 안에 발생)을 운영 코드가 문서 ID 문자열 순으로 처리한다. 사실상 임의 순서다. BM25 우선이 holdout에서 순증 2문항으로 약간 낫다([retrieval-experiments.md](retrieval-experiments.md) 실험 4).
- 정답이 후보 풀(Dense 12 + BM25 12)에 있는데 상위 3건에 못 드는 문항이 196개다. 리랭킹 후보 과제다.
- 건강 컬렉션(ko-sroberta)과 보고서 컬렉션(bge-m3)의 임베딩 모델이 다르다. 건강 컬렉션도 bge-m3로 바꿀 때의 효과는 측정하지 않았다.

## 라우터

- ~~기존 라우터가 "강아지와 **상관**없는 …" 질문을 `analysis`로 잘못 분류한다.~~ 2026-10-04 키워드를 "상관관계"로 바꿔 해결([router.md](router.md)).

## 배포·검증

- **배포 앱 콜드 스타트 (2026-10-04 확인):** 앱이 잠자기 상태면 면접관도 "Zzzz" 화면과 깨우기 버튼을 먼저 본다. 깨어난 직후 첫 실행에서 RAG 페이지가 numpy import 오류(`ImportError`, 부분 초기화)로 한 번 멈췄고, 새로고침하자 정상이었다. 동시에 들어온 첫 import가 충돌한 것으로 추정한다. 재현과 원인은 확인하지 못했다. 면접 직전에 앱을 미리 깨워 두는 것이 가장 확실한 대처다.

- ~~(2026-10-04) 임베딩 전환 결정 대기~~ → 건강은 ko-sroberta, 보고서는 OpenAI로 확정했다. 메모리는 1,765MB(+답변 표 19MB), Chroma DB는 209MB다([deployment-resources.md](deployment-resources.md)).
- ~~`qa.output`을 Chroma 메타데이터에 넣어 sqlite가 커지는 문제~~ → 2026-10-04 해결. 답변은 CSV에서 읽고, Chroma DB는 209MB가 됐다.
- 보고서 PDF가 `data/`에서 `data/source/`로 옮겨졌다. 앱 코드는 새 위치에 맞게 고쳤지만, 커밋할 때 `data/source/*.pdf` 5개를 함께 올려야 배포 앱에서 미리보기가 된다. `data/source/`의 나머지 파일(zip, xls, csv)은 앱이 쓰지 않는다.

- **메모리 한도 초과 위험 (2026-10-02 측정):** 건강 검색 구성 요소와 보고서용 bge-m3를 모두 올리면 약 3.2GB로, Cloud 한도 2.7GB를 넘는다. 리랭커는 더 무겁다. 임베딩 모델을 하나로 줄이는 것이 우선이다([deployment-resources.md](deployment-resources.md)).

- ~~Streamlit Cloud(HTTPS)에서 위치 권한 동작을 확인하지 않았다.~~ 2026-10-02 부분 확인([safety-and-evidence.md](safety-and-evidence.md)). 남은 것은 실제 기기 권한 팝업에서 허용, 거부, 시간 초과를 사람이 직접 확인하는 일이다.
- 배포가 두 곳이다. `dograg-n4gxibufynkgiuixfrkx2v.streamlit.app`(`rndigkwk/dograg` main, 최신)과 `mle-01-p1-team2-…streamlit.app`(`encore-ai-campus/mle-01-p1-team2`, 2026-09-18 README 최종본에서 멈춤). 발표 자료나 노션에 옛 주소가 남아 있으면 혼동될 수 있다.
- ~~로컬 `pyproject.toml`에 `typesafe-sdk`(Jev 섀도 실험 전용)가 앱 의존성으로 추가돼 있었다.~~ 2026-10-02 커밋하지 않고 되돌렸다. 섀도 스크립트는 `uv run --with typesafe-sdk==0.7.1`로 실행한다.
- 응급 신호 문구와 규칙을 수의사가 검토하지 않았다. 규칙만으로는 처음 보는 표현의 응급 질문을 절반쯤 놓쳐(holdout 9/20) Decisions 두 번째 판단을 붙였다(19/20). 평가셋 라벨도 수의사 검토 없이 매겼다([기록](safety-and-evidence.md)).

## 코드 구조

- (2026-10-06 해결) 도구를 `src/tools/`(router, health, report, places, general, review)로, 설정과 공유 자원을 `src/settings.py`·`src/resources.py`로 옮겼다. `pages/rag.py`에는 화면 코드만 남았다(280줄). 설계와 결과: `docs/design/modular-tools-and-conversation-memory.md`
- **CRAG v2 평가 완료 (2026-10-05):** 건강 상담은 켜는 것을 권장한다(보류 대상 80% 보류, 과잉 보류 1/19, 토큰 2배). 보고서는 판정이 정답 근거를 걸러 내서 끈다(정답 페이지 12/18 → 10/18). 2026-10-05 설정을 나눴다. 배포 앱은 건강 상담에만 CRAG를 쓴다([safety-and-evidence.md](safety-and-evidence.md)).
- ~~**라우터 오분류(평가 중 발견)**~~ → 2026-10-04 해결. 키워드 신호가 충돌하면 LLM 라우터에 맡기도록 바꾸고 건강 키워드를 보강했다. 평가셋 오분류 4건이 모두 바로잡혔다([router.md](router.md)).
