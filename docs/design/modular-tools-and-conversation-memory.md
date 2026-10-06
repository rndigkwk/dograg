# 설계: 도구 모듈 분리와 대화 저장·기억

작성 2026-10-06 · 상태: 검토용 초안

## 0. 요약

네 단계로 진행한다. 앞 단계가 뒤 단계의 토대가 되므로 순서를 바꾸지 않는다.

| 단계 | 내용 | 바뀌는 동작 | 외부 의존 |
| --- | --- | --- | --- |
| 1 | `pages/rag.py`의 도구를 `src/tools/`로 분리 (Modular RAG) | 없음 | 없음 |
| 2 | 대화·프로필 저장소 계층 (인터페이스 + 메모리 구현 + Supabase 구현) | 없음 | Supabase (선택) |
| 3 | 선택적 로그인, 스레드별 대화 저장 화면 | 로그인한 사용자만 대화가 저장됨 | Google OAuth, Supabase |
| 4 | 반려견 프로필(장기 기억)과 저장 확인 | 프로필이 검색 필터·답변에 반영됨 | Supabase |

지키는 원칙:
- **서버 RAM:** Streamlit Community Cloud가 보장하는 메모리는 690MB다(최대 2.7GB). 지금 앱의 최대 메모리는 약 1GB다. 대화 저장과 기억이 RAM을 쓰면 안 된다. 열린 대화의 최근 몇 턴 외에는 서버에 올리지 않는다.
- **핵심 데이터는 저장소 안 파일로 둔다.** 벡터, BM25, 병원·장소 같은 답변에 꼭 필요한 데이터가 여기에 해당한다. Supabase는 "없어도 답변은 되는" 데이터(대화 기록, 프로필)에만 쓴다. Supabase가 정지돼도 챗봇은 동작해야 한다.
- **CI와 단위 테스트는 네트워크 없이 돈다.** 외부 서비스는 인터페이스 뒤에 두고 메모리 구현으로 테스트한다.
- **측정으로 결정한다.** 각 단계는 아래 "완료 기준"의 수치를 확인한 뒤 병합한다.

## 1. 현재 구조 (2026-10-06, `main` 기준)

- `pages/rag.py`는 1,279줄이다. 화면 코드, 라우터, 건강·보고서·병원 도구, 설정, 프롬프트, 캐시 로더가 모두 들어 있다.
- 그래프(`src/chat_graph.py`)는 이 파일의 함수 18개를 `_PageTools`를 통해 부른다. `_PageTools`는 Streamlit이 이 파일을 모듈이 아니라 스크립트로 실행하기 때문에 넣은 우회 장치로, 호출 시점에 `globals()`에서 함수를 찾는다.
  - 라우터: `classify_question`, `is_date_question`, `current_date_answer`
  - 건강: `build_rag_search_query`, `infer_rag_filters`, `retrieve_health`, `generate_health_answer`, `ask_rag`, `detect_urgent_sign`
  - 보고서: `analyze_report`, `search_reports`, `generate_report_answer`, `report_evidence_from_docs`
  - 병원: `run_sql_search`
  - 일반: `answer_without_tool`
  - CRAG LLM 호출: `review_evidence`, `rewrite_search_query`, `decompose_question`
- `@tool`이 붙은 `rag_tool`, `sql_tool`, `report_analysis_tool`은 어디에서도 호출되지 않는다. 예전 도구 호출 방식의 흔적이다.
- `pages.rag`를 import하는 파일이 20개다(테스트 12, 스크립트 8). 테스트는 `patch.object(rag, ...)`로 함수와 상수를 바꿔치기한다. 가장 많은 것은 `load_chat_model` 15회, `load_report_vector_db`와 `initialize_rag` 각 4회다.
- 대화 기록은 `st.session_state`에 최근 6턴만 둔다. 새로고침하면 사라진다.
- 실행 로그(`output/chat_runs.jsonl`)는 질문 원문 대신 해시와 길이만 남긴다. Cloud 디스크는 임시라서 재부팅하면 사라진다.
- 병원 데이터 `data/hospital.db`는 `hospital(ids, name, new_address, x_coor, y_coor, old_address)` 5,448행이다.
  - 영업상태와 전화번호가 없다.
  - 좌표는 대부분 EPSG:5174인데, 208건은 경위도로 보인다.

## 2. 단계 1: 도구 모듈 분리 (Modular RAG)

### 목표 구조

```text
src/
├── settings.py          # get_setting, setting_enabled, crag_enabled, get_openai_api_key
├── resources.py         # st.cache_resource 로더: 벡터 DB, BM25, 답변 표, 채팅 모델, 보고서 DB
├── tools/
│   ├── __init__.py      # Toolset: 그래프가 쓰는 함수 묶음
│   ├── router.py        # classify_question, 키워드, ROUTER_PROMPT, 날짜 질문
│   ├── health.py        # 필터 추론, 검색어, retrieve_health, 생성, RAG_PROMPT
│   ├── report.py        # 보고서 검색·분석, REPORT_ANALYSIS_PROMPT, 목차 주제
│   ├── places.py        # 병원 SQL 검색, SQL 검증, 거리 정렬 (나중에 약국·장묘업으로 확장)
│   ├── general.py       # answer_without_tool
│   └── review.py        # review_evidence, rewrite_search_query, decompose_question
├── chat_graph.py        # 그대로 (Toolset을 받음)
└── ...                  # 기존 모듈 그대로
pages/rag.py             # 화면만: render_page, render_assistant_message, progress_message, 워밍업
```

### 설계 결정

- **`_PageTools`를 `Toolset`으로 바꾼다.** `Toolset`은 정해진 이름을 해당 모듈에서 **호출 시점에** 찾는다. 테스트가 `patch.object(health, "retrieve_health", ...)`처럼 모듈 속성을 바꿔도 그래프에 반영되도록 하기 위해서다. 그래프가 쓰는 이름 목록을 `Toolset`에 명시해서, 오타는 import 시점에 드러나게 한다.
- **캐시 로더는 `src/resources.py`로 모은다.** `st.cache_resource`는 모듈에서도 동작한다. 경로 상수(`CHROMA_DIR`, `DB_PATH` 등)도 여기에 두어, 테스트가 바꿔치기할 곳을 하나로 모은다.
- **쓰지 않는 `@tool` 래퍼 3개는 지운다.**
- **동작은 바꾸지 않는다.** 프롬프트, 키워드, 상수 값은 옮기기만 한다.

### 옮기는 순서 (PR 3개)

1. **1-A:** 모듈을 만들고 함수를 옮긴다. `pages/rag.py`에서는 옮긴 이름을 다시 export해서 기존 테스트와 스크립트가 그대로 돌게 한다.
2. **1-B:** 테스트 12개와 스크립트 8개의 import와 patch 대상을 새 모듈로 바꾼다.
3. **1-C:** `pages/rag.py`의 다시 export하는 코드와 `_PageTools`를 지운다.

### 완료 기준

- 단위 테스트가 모두 통과한다(현재 127개).
- 라우팅: CRAG 평가 60문항의 경로가 분리 전과 같다(모델 없이 도는 라우터 테스트로 확인).
- 검색: 검증 561문항 하이브리드 `hit@3` 0.2638 그대로다.
- 메모리: `scripts/measure_memory.py` 최대값이 ±5% 안이다(현재 985MB).
- 로컬 `streamlit run`에서 건강·보고서·병원 질문이 각 1회 정상 동작한다.

## 3. 단계 2: 저장소 계층

### 인터페이스

```python
class ConversationStore(Protocol):
    def create_thread(self, user_id: str, title: str) -> str: ...
    def list_threads(self, user_id: str, *, limit: int = 20, before: datetime | None = None) -> list[ThreadSummary]: ...
    def recent_messages(self, thread_id: str, *, turns: int = 6) -> list[Message]: ...
    def append_turn(self, thread_id: str, question: str, answer: str, *, route: str, evidence_ids: list[str]) -> None: ...
    def delete_thread(self, user_id: str, thread_id: str) -> None: ...
    def delete_user(self, user_id: str) -> None: ...

class ProfileStore(Protocol):
    def get(self, user_id: str) -> PetProfile | None: ...
    def upsert(self, user_id: str, profile: PetProfile) -> None: ...
    def delete(self, user_id: str) -> None: ...
```

구현은 두 가지다.
- `InMemory*`: 테스트용이자 로그인하지 않은 사용자용. 세션 안에서만 유지되며 지금과 같은 동작이다.
- `Supabase*`: `supabase-py`(이미 의존성에 있음)로 REST 호출. 서비스 키는 서버 secrets에만 두고 브라우저로 보내지 않는다.

**REST를 쓰는 이유:** Postgres에 직접 연결하면 Streamlit의 재실행과 다중 세션 속에서 연결 풀을 관리해야 한다. HTTPS 요청은 상태가 없어 단순하다.

### 스키마 (Supabase Postgres)

```sql
create table threads (
  id uuid primary key default gen_random_uuid(),
  user_id text not null,              -- sha256(OIDC sub + salt), 이메일은 저장하지 않음
  title text not null,                -- 첫 질문 앞 30자 (LLM 호출 없음)
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);
create index on threads (user_id, updated_at desc);

create table messages (
  id bigint generated always as identity primary key,
  thread_id uuid references threads(id) on delete cascade,
  role text check (role in ('user', 'assistant')),
  content text not null,
  route text,                         -- rag / sql / analysis / none
  evidence_ids text[],                -- 근거 원문은 저장하지 않고 ID만
  created_at timestamptz default now()
);
create index on messages (thread_id, id desc);

create table pet_profiles (
  user_id text primary key,
  profile jsonb not null,             -- 4장의 PetProfile
  updated_at timestamptz default now()
);
```

- **보관 기간:** 마지막 활동 후 30일이 지난 스레드는 삭제한다(예약 작업). 기간은 열린 질문이다.
- **용량:** 메시지 하나를 약 1.5KB로 잡으면 무료 500MB에 약 30만 개가 들어간다. 포트폴리오 규모에서는 충분하다.

### 장애 처리 (Supabase 정지·장애)

- 요청마다 타임아웃을 2초로 둔다. 실패하면 5분 동안 Supabase를 건너뛰는 차단기(circuit breaker)를 연다. 그동안은 메모리 구현으로 동작하고, 화면에 "지금은 대화가 저장되지 않습니다"라고 안내한다.
- 저장은 답변을 화면에 보여 준 뒤에 한다. 저장이 실패해도 답변에는 영향이 없다.
- 무료 플랜은 1주일 동안 활동이 없으면 정지된다. GitHub Actions로 며칠마다 가벼운 조회를 보내 활동을 유지한다. 이 방식이 Supabase 정책과 맞는지는 적용 전에 확인한다.

### RAM

- 클라이언트 하나를 `st.cache_resource`로 공유한다.
- 대화 기록은 캐시하지 않는다. 열린 스레드의 최근 6턴과 스레드 목록 20개만 세션에 둔다.
- 교안 day51의 `InMemorySaver`처럼 모든 사용자의 상태를 서버 메모리에 쌓지 않는다.

### 완료 기준

- 두 구현이 **같은 계약 테스트**를 통과한다.
  - 메모리 구현: CI에서 항상 실행한다.
  - Supabase 구현: `SUPABASE_TEST_URL`이 있을 때만 로컬에서 실행한다.
- 차단기 테스트: 가짜 클라이언트가 타임아웃을 내면 두 번째 호출부터 바로 메모리 구현으로 간다.
- 측정 스크립트로 잰 최대 메모리 증가가 20MB 이하다.

## 4. 단계 3: 사용자 구분과 스레드별 대화 저장

### 사용자 구분

- **Streamlit 내장 로그인(`st.login`, Google OIDC)을 선택 사항으로 붙인다.**
  - 필요한 것: `[auth]` secrets 설정, Authlib 의존성, Google OAuth 클라이언트(배포 URL을 리디렉션 주소로 등록).
  - 로그인하지 않으면 지금처럼 세션 안에서만 동작한다. 포트폴리오를 보는 사람이 로그인 없이 바로 써 볼 수 있어야 한다.
- `user_id`는 OIDC `sub`에 서버 비밀값(salt)을 더해 SHA-256으로 만든다. 이메일과 이름은 저장하지 않는다.

### 개인정보 (지금 원칙에서 바뀌는 부분)

지금은 질문 원문을 남기지 않는다. 대화 저장은 원문을 보관하는 것이므로 다음을 지킨다.
- 처음 로그인할 때 저장 동의를 받는다. 동의하지 않으면 로그인해도 세션 모드로 동작한다.
- "이 대화 삭제"와 "내 데이터 모두 삭제" 버튼을 둔다. 삭제는 즉시 DB에서 지운다.
- 보관 기간은 30일이다(3장).
- 실행 로그는 지금처럼 해시와 길이만 남긴다. 대화 저장과 분리한다.

### 화면

- 사이드바:
  - "새 대화" 버튼
  - 최근 스레드 20개(제목, 날짜), 누르면 그 스레드를 연다
  - 삭제 버튼
- 스레드를 열면 최근 6턴을 불러와 화면에 그린다. 그래프에는 지금처럼 `chat_history`로 넘긴다.
- 답변이 끝나면 질문과 답변 한 쌍을 저장한다.

### LangGraph 체크포인터를 쓰지 않는 이유

교안 day51의 `SqliteSaver`/`PostgresSaver`는 노드가 끝날 때마다 State 전체를 저장한다.
- 우리 State에는 검색 문서가 5~12건 들어 있어서 용량을 빨리 쓴다.
- 질문당 DB 왕복이 6~8번 생겨 답변이 느려진다.
- 체크포인터가 꼭 필요한 경우는 실행 중간에 멈췄다 이어 가는 것(`interrupt`)인데, 이 앱에는 아직 없다.

그래서 "질문 하나가 끝났을 때 결과만 저장"한다. HITL이 필요해지면 그때 체크포인터를 다시 검토한다.

### 완료 기준

- `AppTest` 기반 테스트(가짜 저장소, 가짜 `st.user`)로 확인한다.
  - 로그인과 비로그인 각각에서 대화 흐름이 정상이다.
  - 스레드를 전환하면 기록이 바뀐다.
  - 삭제가 동작한다.
- 배포 앱에서 직접 확인한다.
  - 로그인 → 대화 → 새로고침 → 기록이 유지된다.
  - Supabase를 일부러 끊으면 안내가 나오고 답변은 계속된다.

## 5. 단계 4: 반려견 프로필 (장기 기억)

### 형식

교안 day52의 Mem0는 자유 문장으로 기억을 쌓는다. 이 앱에 필요한 기억은 형식이 정해져 있어서 스키마로 저장한다. 라이브러리 메모리와 기억을 만들 때마다 드는 LLM 호출이 필요 없다.

```python
class PetProfile(BaseModel):
    name: str | None
    breed: str | None
    birth_month: date | None        # 연령 단계는 여기서 계산
    weight_kg: float | None
    neutered: bool | None
    conditions: list[str] = []      # 지병
    medications: list[str] = []     # 복용약
    allergies: list[str] = []
```

### 입력

1. **사이드바 "우리 아이 정보" 폼:** 직접 입력하고 수정한다. 이것이 기본 경로다.
2. **대화 중 감지 후 확인:** 건강 질문 답변이 끝난 뒤, LLM이 질문에서 프로필 정보를 찾으면 "생후 3개월로 저장할까요?" 버튼을 보여 준다. 사용자가 누를 때만 저장한다.
   - 잘못된 기억이 쌓이는 것을 막는다.
   - 확인은 화면에서 받는다. 그래프 `interrupt`를 쓰지 않으므로 체크포인터가 필요 없다.
   - 감지 호출은 로그인한 사용자의 건강 경로에서만 한다. 토큰 증가는 평가로 잰다.

### 활용

- **연령 필터:** 질문에 나이가 없으면 프로필의 생년월로 연령 단계(자견/성견/노령견)를 정한다. 질문에 나이가 있으면 질문이 우선한다.
- **답변 프롬프트:** 지병, 복용약, 알레르기를 "참고 정보"로 넣는다. 프롬프트 규칙(근거에 있는 것만 쓰기)은 그대로다. 프로필만 보고 진단하지 않는다.
- **진료비 조회:** 진료비 데이터를 추가하면 체중 구간을 자동으로 고른다.
- `ChatState`에 `pet_profile`을 더하고, `infer_rag_filters`가 이를 받는다.

### 완료 기준

- 나이 없는 건강 질문 20개에 프로필을 넣고 연령 필터가 맞게 걸리는지 확인한다(단위 테스트).
- 충실도 평가(`scripts/evaluate_faithfulness.py`)를 프로필 있음/없음으로 돌린다. 근거 밖 주장이 늘지 않아야 한다.
- 감지 호출의 토큰과 지연 증가를 기록한다.

## 6. 병행 트랙 (이 문서 범위 밖, 단계 1 이후 가능)

- **장소 데이터:** `places.py`를 병원 전용이 아닌 공통 장소 테이블로 확장한다. 컬럼은 종류, 이름, 주소, 좌표, 전화, 영업상태다.
  - 병원: `data/source/동물_동물병원.csv`(영업 중 5,459곳, 전화·영업상태 포함)로 다시 만든다. 좌표계도 정리한다.
  - 동물약국 13,692곳, 장묘업 88곳을 추가한다.
- **진료비 통계:** 농림축산식품부 동물병원 진료비 공개 자료(항목 × 시·군·구 × 중간·평균·최저·최고)를 `fees` 테이블로 넣는다. 공식 파일이나 API가 없으므로 수집 경로부터 확인한다.
- **관측:** Langfuse 트레이싱. 질문·답변은 마스킹한다.
- **평가셋 확대:** AI Hub 검증 Q&A 2,400건(현재 561건 사용).

## 7. 열린 질문

1. 대화 보관 기간: 30일이 적당한가? 보관하지 않는 선택지도 둘까?
2. Google 로그인만으로 충분한가? 다른 OIDC 제공자도 필요한가?
3. Supabase를 활성 상태로 유지하는 예약 작업이 정책상 괜찮은가? 안 된다면 정지 시 안내만으로 충분한가?
4. 프로필 감지 호출을 기본으로 켤까, 사용자가 켜게 할까?
5. 개인정보 처리 안내 문구는 어디에 어떤 수준으로 둘까?

## 8. 대략적인 작업량

| 단계 | 예상 | 주요 위험 |
| --- | --- | --- |
| 1 분리 | 1~1.5일 | 테스트 patch 대상 변경이 많음(20개 파일) |
| 2 저장소 | 1일 | Supabase 정지 처리와 계약 테스트 |
| 3 로그인·스레드 | 1~1.5일 | OAuth 설정, Streamlit 재실행 모델 속 상태 관리 |
| 4 프로필 | 1일 | 감지 정확도, 프롬프트 영향 평가 |
