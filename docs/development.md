# 개발과 실행

README에서 옮긴 실행 방법과 저장소 구조입니다. 구조 설명은 [architecture/](architecture/README.md), 배포 절차는 [runbook-manual-deploy.md](runbook-manual-deploy.md)와 [docker-deployment.md](docker-deployment.md)에 있습니다.

## 데이터

AI Hub 데이터는 재배포할 수 없어 저장소에 없습니다. 앱은 비공개 Hugging Face 데이터셋에서 `HF_TOKEN`(읽기 권한)으로 받습니다(`src/private_data.py`, 리비전 고정). 데이터 없이도 단위 테스트는 돌고, 데이터가 필요한 테스트는 건너뜁니다.

## 로컬 실행

설치:

```bash
uv sync
```

API:

```bash
uv run uvicorn api.main:app --port 8000
```

웹:

```bash
npm --prefix web install
```

```bash
npm --prefix web run dev
```

- 웹은 `NEXT_PUBLIC_RAGDOG_API_URL=http://localhost:8000`으로 로컬 API를 씁니다.
- 키는 `.env`(OpenAI, Supabase)에 두고 Git에 올리지 않습니다. 예시는 `.env.example`에 있습니다.
- `SEARCH_BACKEND`가 없으면 검색은 로컬 Chroma + Kiwi BM25로 돕니다. 운영과 같은 검색은 `SEARCH_BACKEND=supabase`와 DB 주소가 필요합니다([retrieval.md](architecture/retrieval.md)).
- Streamlit 화면: `uv run streamlit run main.py`는 새 주소 안내만 띄웁니다. 전체 화면은 `STREAMLIT_FULL_APP=1`을 함께 줍니다.

방문 준비 보고서 팀만 CLI로:

```bash
uv run python -m team.main "4살 말티즈가 어제부터 설사를 하고 오늘 아침에 두 번 토했어요." --region 강남구
```

## 테스트

Python:

```bash
uv run python -m unittest discover -s tests
```

웹(vitest):

```bash
npm --prefix web test
```

- 평가 스크립트(`scripts/evaluate_*.py`, `scripts/langfuse_experiments.py`)는 실제 모델을 불러 비용이 듭니다. 실행 전에 예상 호출 수를 보여 주고, 200번을 넘으면 확인을 받습니다(`scripts/cost_guard.py`).
- CI에서 도는 것과 병합 조건은 [operations.md](architecture/operations.md)에 있습니다.

## 저장소 구조

```text
.
├── web/                    # Next.js 화면: 상담, 방문 준비, 보고서, 시설, 진료비, 관리 일정, 상담 기억, 소개
├── api/                    # FastAPI: /chat(SSE), /visit-prep, /places, /fees, /memory, /stats, /feedback
├── src/
│   ├── chat_graph.py       # LangGraph 상담 그래프: 라우팅, CRAG, 복합 질문, 보류
│   ├── tools/              # 그래프의 도구: router, health, report, places, fees, history, urgency, notes …
│   ├── rails.py · crisis.py · pii.py   # 입력·검색·답·출력·실행 레일 (rails/rails.yml)
│   ├── hybrid_retrieval.py # BM25 색인, RRF
│   ├── supabase_store.py   # pgvector 검색, 장애 시 로컬 대체
│   ├── model_outage.py     # 모델 한도 소진 시 검색 결과만 보여 주기
│   ├── visit_prep_store.py # 멈춘 방문 준비 실행 (Postgres 체크포인터)
│   ├── prompt_versions.py  # 프롬프트 해시 (트레이스·평가 기록)
│   └── auth.py · rate_limit.py · tracing.py · private_data.py
├── team/                   # 멀티에이전트 팀: core → tools → agents → graph → main
├── rails/                  # 레일 규칙 표
├── app_pages/ · main.py    # Streamlit 화면 (지금은 안내만, STREAMLIT_FULL_APP=1이면 전체)
├── scripts/                # 평가, 실험, 회귀 판정, 카나리 점검, SLO, 데이터 빌드, OCR, MLflow, gcp/, sql/
├── notebooks/              # Colab 노트북: 임베딩 미세조정, 채점기 증류, OCR 비교
├── tests/                  # 단위·회귀 테스트, 평가 문항(tests/data/), 기준선(tests/data/baselines/)
├── .github/workflows/      # 테스트, PR 품질 검사, 배포, 롤백, 주간 회귀, SLO, 점검, 알림
└── docs/                   # 구조, ADR, wiki, 보안, 개선 기록, 데이터 명세
```
