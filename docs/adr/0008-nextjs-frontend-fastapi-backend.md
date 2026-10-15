# ADR-0008: 화면을 Next.js로, 앱 로직을 FastAPI로 나누고, 로그인은 Supabase Auth + RLS로

- **상태:** 채택 (2026-10-15). 화면을 Next.js로 옮기는 것은 소유자가 정했다("포트폴리오 가치", 수업 요건 없음). 아래 "정할 것" 네 가지도 소유자가 추천안대로 정했다.
- **이전 기록:** 마지막 Streamlit 버전은 `streamlit-backup` 브랜치(보호됨)와 `streamlit-final` 태그(337b3df)에 고정했다. 그 버전은 Streamlit Cloud 백업 앱에서 자체 Chroma 검색으로 돈다([docker-deployment.md](../docker-deployment.md)).

## 맥락

**지금 구조:** Streamlit 한 프로세스가 화면과 앱 로직을 모두 맡는다. Cloud Run에 하나, 백업으로 Streamlit Cloud에 하나 있다.
- 화면 코드는 Streamlit 전용이다. 페이지 6개, 사이드바, 브라우저 저장소·위치 부품, 약 2,600줄이다.
- 화면 테스트도 Streamlit AppTest로 되어 있다.
- 앱 로직은 `src/`에 있고 Streamlit에 묶여 있지 않다. LangGraph 챗봇, 검색, 시설 DB, 방문 준비 팀, 안전 규칙, 개인정보 가림, 질문 횟수 제한이 여기 있다. 평가 스크립트와 CI도 이 함수를 직접 부른다.

**옮기는 이유:**
1. **로그인과 서버 장기 기억.** 사용자별 기록을 DB가 직접 지키게 하려면 사용자 신원이 DB까지 가야 한다(Supabase Auth의 `auth.uid()`와 행 단위 정책).
   - 지금은 앱이 하나의 계정으로 접속한다. 그래서 사용자 구분을 앱 코드만 지킨다. 조회 하나가 사용자 조건을 빠뜨리면 남의 기록이 보인다.
   - Streamlit의 `st.login`(Google)은 Supabase Auth와 맞물리지 않는다.
2. **화면 제어.** 모바일, 스트리밍, 상태 관리를 마음대로 하기 어렵다.
   - Streamlit은 위젯을 바꿀 때마다 스크립트 전체를 다시 실행한다.
   - 배포 뒤 예전 모듈이 남는 문제가 세 번 있었다(ImportError, AttributeError).
3. **포트폴리오 가치** (소유자 결정).

**지켜야 할 것:**
- 답변 품질은 그대로여야 한다. 지금 평가 세트와 주간 회귀가 기준이다.
- 비용: 무료 한도 안(Supabase 500MB, Langfuse, Cloud Run 무료 사용량), 질문 횟수 제한 유지.
- 안전 장치 유지: 응급 안내가 먼저, 개인정보 가림, 근거 없으면 보류, 공개 API 차단, 앱 전용 DB 계정.

## 결정 (제안)

### 1. 구성
```mermaid
flowchart LR
    B[브라우저<br/>Next.js 화면] -->|HTTPS, Supabase JWT| API[FastAPI<br/>Cloud Run 서울]
    B -->|로그인, 내 기록 읽기·쓰기<br/>사용자 JWT, RLS| SB[(Supabase)]
    API -->|ragdog_app 계정<br/>검색·기록·횟수| SB
    API --> OAI[OpenAI]
    API --> SQL[(시설 SQLite<br/>컨테이너 안)]
    V[Vercel] -.배포.-> B
```

| 부분 | 선택 | 이유 |
| --- | --- | --- |
| 화면 | **Next.js(App Router, TypeScript)를 Vercel에 배포** | PR마다 미리보기 주소가 생긴다. 무료 플랜. Next.js 기본 배포처 |
| 앱 로직 | **FastAPI가 `src/`를 그대로 감싼다. Cloud Run 서울(ADR-0006)** | 파이썬 로직, 평가, 데이터 파이프라인을 다시 짜지 않는다. 지금 Docker 이미지와 배포 흐름을 그대로 쓴다 |
| 답변 스트리밍 | **POST + Server-Sent Events 형식 응답**(`fetch`로 읽음) | 질문이 길고 대화 이력과 프로필을 함께 보내야 해서 GET 기반 `EventSource`는 맞지 않는다. 이벤트 종류: `step`(진행 단계), `token`(답변 글자), `urgent`(응급 안내, 답보다 먼저), `result`(경로·근거·trace id), `error` |
| 로그인 | **Supabase Auth(Google)** | 브라우저와 API가 같은 JWT를 쓴다. DB 정책이 `auth.uid()`로 사용자별 접근을 막는다 |
| 사용자 기록 | **화면이 사용자 JWT로 Supabase에 직접 읽고 쓴다. 표마다 `user_id = auth.uid()` 정책** | 앱 로직(API)은 사용자 기록 표를 아예 만지지 않는다. API 코드 버그로 남의 기록이 샐 길이 없다 |
| 검색 표 | 지금처럼 `ragdog_app`만 읽는다. 공개 API는 계속 막는다 | ADR-0007, 앱 전용 계정(2026-10-15) |
| 비로그인 사용자 | 지금처럼 **브라우저에만 저장**. 로그인하면 "이 기기의 기록을 계정으로 옮길까요?"를 묻는다 | 로그인은 선택이다. 서버 저장은 동의한 사람만 |
| 브라우저가 API를 부르는 방식 | **브라우저에서 API로 직접**(CORS: Vercel 주소만 허용) | Vercel 함수를 거치면 스트리밍 시간 제한과 비용이 붙는다 |

### 2. API (첫 판)
| 경로 | 하는 일 | 지금의 대응 |
| --- | --- | --- |
| `POST /chat` (스트림) | 질문, 대화 이력(최근 6턴 + 요약), 반려견 프로필, 위치(선택) → 답변 | `chatbot()` + `on_token`/`on_step`, 응급 규칙, 질문 횟수 제한 |
| `POST /memory/suggest` | 질문 + 지금 프로필 → 기억할 새 사실 | `profile.suggest_memory` |
| `POST /feedback` | 👎 이유, 동의한 대화 저장 | `tracing.record_feedback*`, `feedback_store` |
| `GET /places` | 지역·종류·좌표로 시설 검색 | `app_pages/hospital.py`의 SQLite 조회, `places.emergency_hospitals` |
| `GET /stats/*` | 데이터 소개 차트 수치 | `app_pages/data.py`, `src/data_charts.py` |
| `POST /visit-prep` → `GET /visit-prep/{id}` | 방문 준비 보고서(1~2분, 모델 호출 10~20회)를 작업으로 시작하고, 진행과 결과를 받는다 | `run_team`, 세션당 3번 제한 |
| `GET /health` | 배포 확인 | keep-alive |

- **질문 횟수 제한:** 로그인했으면 계정 ID로, 아니면 브라우저 ID(헤더)로 센다. 같은 IP 상한도 그대로 둔다(`src/rate_limit.py`).
- **개인정보 가림과 응급 규칙**은 API 안에서 지금처럼 모델 호출 전에 한다. 화면은 규칙을 갖지 않는다.

### 3. 같은 결과인지 확인 (이전하는 동안 답변 로직은 바꾸지 않는다)
- **API 계약 테스트:** `/chat`이 `chatbot()`과 같은 경로·보류 여부·근거 ID를 내는지 본다. 모델은 가짜로 바꿔 끼운다(호출 0).
- **실제 모델로 확인:** CRAG 60 + 라우팅 36을 **API를 거쳐** 한 번 돌린다. 지금 주간 회귀 기준을 넘는지 본다. 모델 호출 약 250번이고, 비용 미리 보기(`scripts/cost_guard.py`)로 확인을 받은 뒤 돌린다.
- **화면 확인:** Playwright로 페이지별 동작을 본다. 질문 → 스트리밍 답 → 근거 → 👎 → 기억 제안. 지금의 AppTest 화면 테스트를 이것으로 옮긴다.
- **배포 확인:** keep-alive를 새 화면 주소로 바꾼다. 커밋 일치, 날짜·건강 질문을 그대로 확인한다.

### 4. 단계
| 단계 | 내용 | 끝났다고 보는 기준 |
| --- | --- | --- |
| **P1 API** | `api/`(FastAPI)를 같은 저장소에 둔다. `ragdog-api`라는 별도 Cloud Run 서비스로 배포한다. Streamlit 서비스는 그대로 둔다 | 계약 테스트 통과, API로 돌린 CRAG·라우팅이 주간 기준 이상, 스트리밍 첫 글자 지연이 지금 수준 |
| **P2 질병 문의 화면** | `web/`(Next.js)에서 채팅, 스트리밍, 근거, 응급 안내, 👎, 기억 제안, 대화 기록(브라우저 저장)을 만든다. Vercel 미리보기 배포 | Playwright 흐름 통과, 모바일 폭 확인 |
| **P3 나머지 화면** | 홈, 데이터 소개(차트), 시설 찾기(위치·지도), 방문 준비 보고서 | 페이지별 흐름 통과 |
| **P4 로그인** | Supabase Auth(Google), 사용자 기록 표와 정책, 기기 기록을 계정으로 옮기기, 내 기록 보기·모두 지우기, 개인정보 안내 | 다른 사용자 JWT로 기록을 읽으면 0행인 테스트, 로그아웃·공용 PC 확인 |
| **P5 전환** | keep-alive와 문서를 새 주소로 바꾸고, Cloud Run의 Streamlit 서비스를 내린다(백업은 Streamlit Cloud에 그대로). `app_pages/`·Streamlit 화면 코드 삭제 | 새 주소로 일주일 운영, 주간 회귀 통과 |

- P1~P3 동안 Cloud Run의 Streamlit 서비스는 지금처럼 주 배포로 남는다. 사용자는 바뀌는 걸 모른다.
- **PR은 단계 안에서도 작게 나눈다**(한 PR = 한 작업). 예: P1을 "API 뼈대와 /health", "/chat 스트림", "/places·/stats", "/visit-prep", "Cloud Run 배포"로 나눈다.

## 정한 것 (소유자, 2026-10-15)
1. **화면 배포처: Vercel.**
   - 미리보기 주소만 보고 고른 것이 아니다. 화면을 Cloud Run에 두면 화면도 0개까지 줄어 첫 화면부터 15~27초가 붙는다. 그렇지 않으려면 최소 1개를 켜 두는 상시 비용이 든다.
   - 화면과 API의 주소가 달라 생기는 CORS는 화면을 Cloud Run에 두어도 똑같이 생긴다.
   - 한 컨테이너에 Node와 Python을 같이 넣으면 CORS는 없어진다. 대신 이미지와 냉시동이 커진다.
   - 답변은 브라우저에서 Cloud Run으로 바로 가므로 Vercel을 거치지 않는다.
   - Vercel 무료 플랜은 비상업용이다. 상업용이 되면 다시 정한다.
2. **API 냉시동: 최소 인스턴스 0(지금처럼).** 페이지가 열리면 `/health`를 한 번 보내, 질문을 입력하는 동안 API를 미리 깨운다.
3. **로그인(P4): Google만.**
4. **저장소: 같은 저장소에 `web/`과 `api/`.** 평가, CI, 문서가 한곳에 남는다.

## 결과

**좋아지는 것**
- 사용자 기록을 DB가 직접 지킨다. 앱 코드 버그가 있어도 남의 기록이 읽히지 않는다.
- 화면과 앱 로직을 따로 배포하고 따로 테스트한다. Streamlit 재실행 모델과 예전 모듈 문제가 사라진다.
- 같은 API를 나중에 앱이나 다른 화면이 재사용할 수 있다.

**나빠지는 것**
- 배포가 둘(Vercel + Cloud Run)이 되고, 둘 사이 인증(JWT 검증)과 CORS를 관리해야 한다.
- 화면 코드를 새로 쓰는 몇 주 동안 Streamlit과 두 벌을 유지한다.
- TypeScript, Next.js 의존성과 화면 테스트 도구가 늘어난다.

**다시 검토할 조건**
- P1의 API로 돌린 품질이 주간 기준 아래면 원인을 찾을 때까지 P2로 가지 않는다.
- Vercel 무료 플랜 조건이 바뀌거나 상업적으로 쓰게 되면 화면 배포처를 다시 정한다.
- 로그인 사용자가 거의 없으면 P4(서버 기록)를 미루고, "기억 내보내기·가져오기"로 대신한다.
- 이전이 실패하면 `streamlit-final`로 돌아간다. Streamlit Cloud 백업 앱과 보호 브랜치가 그 대비다.
