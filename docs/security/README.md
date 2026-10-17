# 라그도그 보안 정리 (현재 상태, 2026-10-17)

이 문서는 **지금 무엇을 어떻게 지키는지**를 한곳에 모은 것이다. 시점별 점검 기록은 따로 있다.
- [2026-10-16 로그인 전 점검](2026-10-16-pre-login-review.md): 질문 한도 우회 2건(높음), SQL 비용, 보안 헤더, API 문서, 의존성
- [2026-10-16 로그인 뒤 점검](2026-10-16-login-review.md): OAuth, 열린 리디렉션, 토큰 위조 7가지, RLS, 계정 삭제
- 이 문서의 [2026-10-17 점검](#2026-10-17-점검-로그인-뒤-새로-생긴-것): 방문 준비 저장소, 상담 노트, 진료비·보고서 탭, MLflow

새 기능이 데이터를 저장하거나 새 경로를 열면 이 문서의 표를 먼저 고친다.

## 1. 무엇을 어디에 두나

| 데이터 | 위치 | 누가 읽고 쓰나 | 보관 |
| --- | --- | --- | --- |
| 로그인 전 대화·반려견 정보 | 브라우저 localStorage | 그 브라우저만 | 사용자가 지울 때까지(대화 20개) |
| 로그인 뒤 대화·반려견 정보 | Supabase `ragdog_user_threads`, `ragdog_user_profile` | 본인만(RLS). API 계정은 권한 없음 | 사용자가 지우거나 계정을 지울 때까지 |
| 지난 상담 노트 | Supabase `ragdog_user_notes` | 본인만(RLS). API 계정은 권한 없음 | 300자, 최대 30개. 사용자가 지우거나 계정을 지울 때까지 |
| 기억 사용 설정 | Supabase Auth `user_metadata.consultation_notes` | 본인 | 계정과 함께 |
| 방문 준비 중 멈춘 실행 | Supabase `visit_prep` 스키마(공개 REST에 노출 안 됨) | API 계정(`ragdog_app`)만 | 상담 문장은 최대 30분. 주인은 salt 해시 |
| 보고서 시작 횟수 | `visit_prep.report_starts` | API 계정만 | 해시와 시각만, 24시간 |
| 질문 횟수 | `ragdog_rate_limit` | API 계정만 | salt 해시와 시각만, 48시간 |
| 👎 뒤 동의하고 보낸 대화 | `ragdog_feedback` | API 계정만(공개 REST 차단) | 개인정보 가림. **3년 뒤 자동 삭제**(소유자 결정 2026-10-17, `scripts/sql/retention.sql`) |
| 자료에 없던 내용 | `ragdog_data_gaps` | API 계정만 | 답변 속 "자료에 ○○은 없습니다" 문장, 가림. 질문은 저장 안 함. **3년 뒤 자동 삭제** |
| 평가·배포 점검 결과 | `ragdog_eval_history`, MLflow(DagsHub) | API 계정 / **MLflow는 누구나 읽기 가능** | 점수와 설정만(아래 5) |
| 실행 기록 | Langfuse | 소유자 | 사용자 문장과 문서 문장은 길이만 남김(`src/tracing.py`) |

- 위치는 브라우저가 버튼을 누를 때만 보낸다. 서버는 저장하지 않는다.
- 서버 디스크에는 사용자 데이터를 쓰지 않는다. 방문 준비 보고서 파일은 임시 폴더에 만들고 바로 지운다.

## 2. 누가 누구인가 (인증)
- **로그인은 Google 하나**다(Supabase Auth, PKCE). 이메일 공급자는 껐다.
- **API의 토큰 검증**(`src/auth.py`): Supabase JWKS(ES256)로 서명·`aud`·`iss`·만료를 확인한다.
  - `alg: none`, HS256 위조, 모르는 kid, 공개 키를 토큰으로 낸 경우는 모두 로그인 안 함으로 본다.
  - 토큰이 위조면 오류를 내지 않고 비로그인으로 처리한다.
- **관리자 키 없음:** service_role 키는 어디에도 두지 않는다. 계정 삭제는 본인만 지우는 DB 함수(`delete_my_account()`)로 한다.
- **로그인 뒤 돌아갈 주소**는 허용 목록(정식·localhost)만 쓴다. 화면 쪽은 `safeReturnPath`가 외부 주소를 홈으로 바꾼다.

## 3. 무엇을 할 수 있나 (권한)
- **사용자 표 3개**(대화, 반려견 정보, 노트)
  - 정책: RLS `user_id = auth.uid()`
  - 권한: `authenticated`에만 있고 `anon`, `public`, `ragdog_app`에는 없다.
  - 화면이 `user_id`를 보내지 않고 DB가 토큰에서 채운다. 남의 이름으로 쓰거나 행을 넘기는 것은 정책이 막는다.
- **앱 표**(검색, 한도, 피드백, 데이터 공백, 평가 기록, `visit_prep`)
  - RLS가 켜져 있고, `anon`과 `authenticated` 권한을 회수했다.
  - API는 앱 전용 계정 `ragdog_app`으로 접속한다(관리자 아님).
- **시설 SQL:** 모델이 만든 SQL은 읽기 전용 SQLite에서 SELECT만 실행한다. 3초, 1,000행 제한이 있다.
- **검사:** `uv run python scripts/check_user_records.py`가 실제 DB에서 롤백 트랜잭션으로 확인한다. 기대 결과는 대화·프로필 11개, 계정 삭제 8개, 노트 13개, 모두 통과다.

## 4. 남용과 비용
- **질문 한도**(`src/rate_limit.py`)
  - 사람당 시간 10번, 하루 30번이다. 로그인하면 계정, 아니면 브라우저 id로 센다.
  - 네트워크당 시간 60번, 하루 200번이 따로 받친다.
  - 접속 주소는 `X-Forwarded-For`의 오른쪽에서 `RAGDOG_PROXY_HOPS`(1)번째 값을 쓴다. 위조로 바꿀 수 없다.
- **한도 면제:** 비밀 헤더 `X-RagDog-Check`가 `RAGDOG_CHECK_TOKEN`과 같을 때만 면제한다(`hmac.compare_digest`). User-Agent로는 면제되지 않는다.
- **모델을 부르는 경로는 모두 질문 한도에 들어간다.**
  - `/chat`
  - 보고서 탭(`/chat` + `route: "report"`)
  - `/visit-prep`: 보고서 하루 2개
  - `/memory/note`: 로그인한 경우만, 계정 기준
- **피드백 저장:** 브라우저당 시간 60건, 네트워크당 300건이다.
- **입력 검증**(pydantic)
  - 질문 1,000자, 좌표 범위, `top_k`, 진료비 항목 길이(60자)
  - 노트 최대 5개, 각 300자, 실제 날짜만
  - `route`는 `"report"`만
  - 어긋나면 422이고, 오류에 내부 정보를 담지 않는다.
- **API 인스턴스:** 최대 2개(비용 상한). 동시에 만드는 방문 준비 보고서는 인스턴스마다 1개다.

## 5. 개인정보
- **모델에 보내기 전에 가린다**(`src/pii.py`). 전화번호, 주소 등을 가리는 대상은 질문, 대화 이력, 상담 노트, 노트를 만들 때의 질문과 답변이다.
- **기록에도 가린다.** Langfuse에는 문장 대신 `[masked N chars]`만 남는다. 데이터 공백과 피드백도 가린 문장만 저장한다.
- **MLflow(DagsHub)는 공개로 둔다**(소유자 결정 2026-10-17, 포트폴리오). 누구나 읽을 수 있다(익명 조회 200 확인).
  - 올리는 것은 점수, 설정, 결과 JSON뿐이다.
  - **상담 문장, 답변, 노트는 올리지 않는다.** 평가 스크립트를 새로 만들 때 이 규칙을 지킨다.
  - 올라간 이름 중 비공개 모델 저장소 이름(`blanden77/kure-v1-dograg`)은 공개 코드에도 있는 이름이라 받아들인다.
- **지난 상담 노트**(ADR-0009)
  - 보호자가 눌러야만 만든다. 기본은 꺼짐이다.
  - `/memory`에서 보고 지울 수 있다.
  - 답변에서는 근거가 아니라 "보호자 기록"으로만 쓴다.

## 6. 웹 화면
- **보안 헤더:** CSP(스크립트·연결·이미지 출처 제한, `frame-ancestors 'none'`), `X-Frame-Options: DENY`, `nosniff`, `Referrer-Policy`, `Permissions-Policy`, HSTS를 붙인다. 2026-10-17에 `/memory`, `/fees`, `/reports`에서 5종 모두 확인했다.
- **화면 코드:** `dangerouslySetInnerHTML`, `innerHTML`, `eval`이 없다. 답변은 react-markdown으로 그리며 HTML을 해석하지 않고, `javascript:` 링크는 막는다.
- **로그인 중 공용 PC:** 로그인 중에는 브라우저에 대화를 새로 쓰지 않는다. 로그아웃하면 토큰과 화면 기록이 사라진다.

## 7. 비밀값
| 비밀 | 어디에 | 누가 만듦 |
| --- | --- | --- |
| OpenAI, Langfuse, `SUPABASE_DB_URL`(앱 계정), `RAGDOG_CHECK_TOKEN`(만든 경우. 없으면 한도 면제가 아예 없음) | GCP Secret Manager(Cloud Run이 읽음) | 소유자 |
| GitHub Actions: `OPENAI_API_KEY`, `LANGFUSE_*`, `HF_TOKEN`, `SUPABASE_DB_URL`, `SEARCH_BACKEND`, `DAGSHUB_TOKEN`, `GCP_WORKLOAD_IDENTITY_PROVIDER` | 저장소 secrets | 소유자 |
| 관리자 DB 주소, DagsHub 토큰(`dagshub`) | 로컬 `.env`(커밋 금지) | 소유자 |
| Supabase publishable 키 | 화면 코드(공개용으로 설계된 키) | — |

- Cloud Run 배포는 키 파일 없이 Workload Identity로 한다.
- 화면 번들에는 API 키와 DB 주소가 없다.
- Colab에서는 토큰을 직접 입력하고, 화면에는 길이만 나온다. 노트북은 마지막에 토큰 변수를 지운다.
- **에이전트(Claude) 작업 규칙:** 비밀값을 출력하지 않고, 비밀번호나 토큰을 만들지 않는다. 운영 DB 변경(테이블 생성 등)은 사용자가 직접 실행한다.

## 8. 받아들인 위험
- **CORS 미리보기 정규식:** 비슷한 이름의 Vercel 프로젝트도 허용될 수 있다. 다만 우리 화면의 토큰은 읽을 수 없고, API는 CORS 없이도 부를 수 있어 새로 열리는 것이 없다.
- **토큰을 localStorage에 둠:** supabase-js 기본값이다. XSS 자체를 CSP와 HTML 미해석으로 막는다.
- **CSP의 `'unsafe-inline'`:** Next.js 부트스트랩과 Leaflet 때문에 남겨 둔다.
- **여러 Google 계정, 브라우저 id 바꾸기:** 네트워크 한도가 받친다.
- **chromadb, oauthlib 취약점:** 해당 서버 기능을 쓰지 않는다. 고친 버전이 나오면 올린다.
- **Supabase 확장이 public 스키마에 있음:** 표는 모두 RLS로 막혀 있다.
- **`delete_my_account` security definer 권고:** 본인만 지우도록 설계했고 테스트로 지킨다.

## 9. 남은 일
1. ~~피드백·데이터 공백의 보관 기간~~ → **3년**으로 정했다(2026-10-17). API 계정에 삭제 권한을 주지 않고, 3년 지난 행만 지우는 DB 함수 `ragdog_expire_old_rows()`를 하루 한 번 부른다.
2. ~~MLflow 공개 여부~~ → **공개 유지**(2026-10-17). "점수와 설정만" 규칙을 지킨다.
3. ~~노트 개수 제한(30) 초과 안내~~ → 노트를 쓰기 전에 개수를 먼저 확인하고, 30개면 모델을 부르지 않고 기억 화면으로 안내한다(2026-10-18).

## 다시 점검하는 법
```bash
uv run python scripts/check_user_records.py
```

- 사용자 표 RLS와 계정 삭제를 확인한다. 실제 DB에서 롤백되고, 모델 호출은 없다.

```bash
uv run python scripts/setup_visit_prep_store.py --check
```

- `visit_prep` 표의 RLS와 권한을 확인한다.
- 배포 뒤에는 위조 토큰, 공개 키 직접 접근, 응답 헤더를 2026-10-17 점검처럼 curl로 다시 본다.

## 2026-10-17 점검 (로그인 뒤 새로 생긴 것)
배포된 서비스에 직접 요청했다. 모델 호출은 없다.

| 시험 | 결과 |
| --- | --- |
| `/memory/note`에 쓰레기 토큰, 공개 키를 토큰으로 | ✅ 401, 모델 호출 전에 거절 |
| 공개 키로 `ragdog_user_notes` 읽기·쓰기 | ✅ `42501 permission denied` |
| 공개 키로 `visit_prep` 스키마 조회 | ✅ `PGRST106` 노출 안 된 스키마 |
| 노트 RLS(실제 DB, 롤백): 남의 노트 읽기·고치기·지우기·넘기기, 남의 이름으로 쓰기, 300자·빈 노트·31번째, 계정 삭제 시 함께 삭제, anon·`ragdog_app` 접근 | ✅ 13개 모두 통과 |
| `/fees`에 SQL 흉내 값, 100자 항목 | ✅ 404, 422(표에서 같은 값만 찾음) |
| `/chat`의 `route: "admin"`, 노트 6개 | ✅ 422 |
| API 문서 `/docs`, `/openapi.json` | ✅ 404 |
| `/memory`, `/fees`, `/reports` 보안 헤더 | ✅ 5종 모두 있음 |
| DagsHub MLflow 익명 조회 | ⚠️ 200(공개). 소유자가 공개 유지로 정함. 상담 문장을 올리지 않는 규칙을 둠(5) |
| 피드백·데이터 공백 보관 기간 | ⚠️ 정해지지 않음 → 3년으로 정하고 자동 삭제를 넣음(남은 일 1) |
