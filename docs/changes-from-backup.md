# dograg_backup → dograg 변경 사항 정리

- 원본: `C:\Users\Playdata\Desktop\dograg_backup` (커밋 `2292ba05`, "Merge branch 'encore-ai-campus:main' into main")
- 수정본: `C:\Users\Playdata\Desktop\dograg` (커밋 `2204acf2` + 커밋하지 않은 변경)
- 비교일: 2026-10-02
- 규모: 커밋된 변경 38개 파일, +2,284 / −46줄. 이와 별도로 커밋하지 않은 변경이 있다(아래 7절).

두 폴더는 같은 git 저장소다. 원본 이후 커밋 5개가 추가됐다.

| 커밋 | 날짜 | 작성자 | 내용 |
| --- | --- | --- | --- |
| `9a269a89` | 09-27 | ohhyuntak | 품질·안전성 개선 설계 문서 |
| `ce324f6f` | 09-28 | ohhyuntak | 하이브리드 건강 검색 적용 |
| `654aedab` | 09-28 | rndigkwk | PR #1 병합 (브랜치 `codex/day47-dense-bm25-rrf`) |
| `1d85ef76` | 09-28 | ohhyuntak | 위치 기반 병원 검색과 품질 안전장치 |
| `2204acf2` | 09-28 | ohhyuntak | origin/main 병합 |

> git 작성자는 사람 계정으로 남아 있어서 Claude와 GPT 중 누가 어떤 부분을 고쳤는지는 기록으로 구분할 수 없다. 브랜치 이름(`codex/...`)으로 보면 하이브리드 검색은 Codex(GPT) 작업으로 추정된다.

---

## 1. 건강 상담(RAG) 검색 품질

### 하이브리드 검색: Dense + BM25 + RRF
- **원본:** Chroma 벡터 유사도 검색만 사용(`db.similarity_search`)
- **수정본:** 벡터 검색 12건과 BM25 키워드 검색 12건을 Reciprocal Rank Fusion(c=60)으로 합쳐 상위 k건을 반환
  - BM25 토크나이저: Kiwi 형태소 분석, 명사·외국어·숫자만 사용
  - BM25 색인은 앱 첫 실행 때 Chroma 문서 19,206건으로 메모리에 만든다(수 분 소요, 이후 캐시)
  - 연령 단계·진료과·질병 필터를 두 검색에 똑같이 적용
- 파일: `src/hybrid_retrieval.py`(신규), `pages/rag.py`의 `ask_rag()`, `load_health_bm25_index()`
- 효과(검증 561건, 메타데이터 일치 기준): hit@3 0.2264 → 0.2620(운영 코드 기준)
- 의존성 추가: `kiwipiepy`, `rank-bm25`

### 데이터 품질 감사
- 학습·검증 CSV의 결측, 중복, 라벨 분포를 원본 수정 없이 기록하는 스크립트를 추가했다.
- 파일: `src/health_quality.py`, `scripts/audit_health_data.py` → `output/health_data_audit.json`

### 문자 n-gram 재정렬 (실험만, 앱에는 미적용)
- 파일: `src/health_retrieval.py`, `tests/evaluate_health_retrieval.py`
- hit@3가 개선되지 않아(0.2264 → 0.2228) 적용하지 않았다.

## 2. 건강 답변 안전장치

- **응급 신호 경고:** 호흡곤란, 의식 소실, 발작·경련, 독성 물질 섭취, 반복되는 헛구역질 같은 표현이 있으면 답변 위에 진료 권고 경고를 표시한다. "호흡곤란은 없어요" 같은 부정 표현은 제외한다.
  - 파일: `src/health_safety.py`(신규), `pages/rag.py`
  - 질문을 입력하는 즉시, 그리고 대화 기록을 다시 그릴 때도 경고가 표시된다.
- **근거가 없으면 LLM을 부르지 않음:** 검색 결과가 0건이면 모델을 호출하지 않고 "근거 부족" 안내를 반환한다(원본은 그대로 모델을 호출).

## 3. 동물병원 검색

### 현재 위치 기반 가까운 병원 (신규)
- 사용자가 "현재 위치 사용" 버튼을 누를 때만 브라우저 위치 권한을 요청한다.
- 병원 좌표(EPSG:5174)를 WGS84로 변환하고, Haversine 직선거리순으로 최대 10곳을 보여준다.
- 위치 좌표는 세션 안에서만 쓰고 DB, 파일, 대화 기록에 저장하지 않는다.
- 권한 거부, 시간 초과, HTTPS가 아닌 환경에서는 안내 메시지를 보여주고 기존 지역 검색을 계속 쓸 수 있다.
- 파일: `src/hospital_distance.py`, `src/location_component.py`(Streamlit components v2)
- 적용 위치:
  - **챗봇(`pages/rag.py`):** "가까운 병원" 질문을 거리순으로 답한다.
  - **병원 찾기(`pages/hospital.py`):** "현재 위치에서 가까운 병원" 섹션에 표와 지도를 추가했다.

### 잘못된 "가까운 병원" 답변 수정
- **원본:** 위치 정보 없이 `LIMIT 1`로 DB의 첫 행을 "가장 가까운 병원"처럼 보여줬다.
- **수정본:** 위치가 없으면 위치 사용이나 지역 검색을 안내한다.

### 병원 상세 화면에서 돌아가기
- `pages/hospital.py`: 병원을 선택한 뒤 목록 검색으로 돌아가는 "다른 병원 찾기" 버튼을 추가했다.

## 4. 보고서 분석 근거 표시

- **원본:** 보고서 분석은 답변 문자열만 반환했고 근거를 보여주지 않았다.
- **수정본:** `analyze_report()`가 답변과 함께 근거(페이지 번호, 발췌문)를 반환한다. 화면에는 근거 목록과 해당 PDF 페이지 이미지(PyMuPDF 렌더링)를 표시한다.
  - 페이지 정보가 잘못됐거나 PDF가 없으면 텍스트 근거만 보여준다.
  - 검색 결과가 없으면 모델을 호출하지 않는다.
  - 모델 호출이 실패하면 오류 대신 안내 문구와 근거를 보여준다.
  - 기존 `report_analysis_tool(question) -> str` 형식은 그대로 유지했다.
- 파일: `src/report_evidence.py`(신규), `pages/rag.py`

## 5. 질문 라우터

- **원본:** 질문에 "병원"이 들어가면 무조건 병원 검색(`sql`)으로 보냈다.
- **수정본:** 판단 순서를 세분화했다.
  1. 범위 밖 질문 → 일반 대화
  2. 보고서 키워드 + "보고서" → 보고서 분석
  3. 병원 + 조회 의도(주소, 근처, 목록 …) → 병원 검색
  4. 건강 키워드(구토, 설사, 기침 …) → 건강 상담
  5. 그 외 병원 관련 → 병원 검색
  - 예: "구토하는데 병원 가야 하나요?"가 이제 병원 목록이 아니라 건강 상담으로 간다.
- **Jev 라우터 비교 (섀도 모드, 앱 동작에는 영향 없음):** `scripts/jev_router_shadow.py`, 질문 40개 `tests/data/jev_router_questions.json`, 의존성 `typesafe-sdk==0.7.1`

## 6. 기타 앱 변경

| 항목 | 원본 | 수정본 |
| --- | --- | --- |
| 생성 모델 | `gpt-5.6-luna`, `temperature=0` | `gpt-6-luna`, temperature 미지정(제공자 기본값) |
| 노트북 평가 모델 | `gpt-5.6-luna` | `gpt-6-luna` (`notebooks/rag_retrieval_evaluation.ipynb`) |
| 홈 화면 대체 이미지 | 로컬 PNG 스크린샷 | `pages/hero_fallback.svg`(신규). 원격 이미지를 불러올 수 없을 때 사용 |
| 대화 기록 다시 그리기 | 답변 텍스트만 저장 | 경로(route), 근거, 안전 경고를 함께 저장해서 다시 그릴 때도 표시 |
| Streamlit 설정 | 없음 | `.streamlit/config.toml`: `fileWatcherType = "none"` |
| CI | 없음 | `.github/workflows/streamlit-ci.yml`: main 대상 PR과 push마다 uv 환경에서 테스트 실행 및 문법 검사 |

## 7. 커밋하지 않은 변경 (2026-10-02 작업)

| 파일 | 내용 |
| --- | --- |
| `src/hybrid_retrieval.py` | `reciprocal_rank_fusion`에 `weights` 인자 추가. 기본값 0.5/0.5라 앱 동작은 같다 |
| `scripts/evaluate_fusion_weights.py`, `tests/test_fusion_weight_sweep.py` | RRF 가중치 실험과 후보 재현율 측정(신규) |
| `tests/test_hybrid_runtime.py` | 가중치 테스트 2개 추가 |
| `README.md` | 하이브리드 검색 설명, 비교 표, 운영 기준 수치, 프로젝트 구조 갱신 |
| `docs/wiki/` | 프로젝트 위키 7개 페이지(신규) |
| `pyproject.toml`, `uv.lock` | 이번 작업 전부터 있던 변경. 위 1·5절의 의존성 추가와 관련됨 |

## 8. 테스트·문서·산출물

- **테스트:** 원본은 2개 파일(`test_rag_refactor_helpers.py`, `test_rag_secrets.py`)이었고, 수정본은 13개 파일, 52개 테스트로 늘었다. 주요 회귀 테스트는 다음과 같다.
  - 응급 신호와 부정 표현, 근거 없음일 때 모델 호출 생략
  - 거리 정렬, 잘못된 좌표 제외, 위치 없는 "가까운 병원" 요청
  - 보고서 페이지 경계, 저장된 대화의 경고·근거 다시 표시
  - 원격 이미지 실패 시 홈 화면, 건강 질문 라우팅 유지
  - GPT-6 모델의 temperature 기본값, 스모크 테스트의 Chroma 복사본 사용
- **실제 DB를 쓰는 테스트:**
  - `tests/chroma_smoke.py`: Chroma를 임시로 복사해서 검색
  - `tests/live_model_smoke.py`: 실제 API를 호출하므로 수동 실행
- **설계 문서:** `docs/superpowers/specs/`, `docs/superpowers/plans/` (설계 1개, 계획 3개)
- **실험 스크립트:** `scripts/evaluate_hybrid_search.py`, `scripts/evaluate_fusion_weights.py`
- **실험 결과:** `output/*.json` 8개. `.gitignore` 대상이라 git에는 올라가지 않는다.

## 9. 배포

| 배포 주소 | 연결 저장소 | 상태 |
| --- | --- | --- |
| <https://dograg-n4gxibufynkgiuixfrkx2v.streamlit.app> | `rndigkwk/dograg` `main` | 이 문서의 1~6절 기능이 반영됨(2026-10-02 확인) |
| <https://mle-01-p1-team2-f5fqyncuwejycn4hyrp64b.streamlit.app> | `encore-ai-campus/mle-01-p1-team2` | 원본 시점(`68b057b4`)에서 멈춤. 위치 기능 등이 없다 |

HTTPS는 Streamlit Cloud가 기본으로 제공한다. 저장소에 HTTPS 관련 설정을 추가한 커밋은 없다.

## 10. 바뀌지 않은 것

- **데이터:** `df.csv`, `df_val.csv`, `hospital.db`, 보고서 PDF는 그대로다. 아키텍처 SVG는 줄바꿈 문자만 다르다.
- **Chroma DB:** 컬렉션별 문서 수가 같다(`pet_care` 19,206, `pet_analysis_1024` 127). 다만 바이너리 파일은 원본과 다르다. 재색인한 흔적은 없으므로, 앱을 실행하면서 원본 경로의 Chroma를 열 때 인덱스 파일이 갱신된 것으로 추정된다.
- **페이지와 공통 모듈:** `pages/data.py`, `main.py`, `src/ui.py`, `src/keys.py`, `src/data_*.py`
- **로컬 설정 파일:** `.env`, `.streamlit/secrets.toml`, `.omc/`, `.uv-cache/`는 수정본에만 있다. 비밀 정보와 캐시라 내용은 비교하지 않았고, `.gitignore` 대상이다.
