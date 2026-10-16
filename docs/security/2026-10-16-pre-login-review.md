# 로그인(P4) 전 보안 점검 (2026-10-16)

ADR-0008 P4(Google 로그인)에 앞서, 지금 공개된 화면(Vercel)과 API(Cloud Run `ragdog-api`), Supabase를 점검했다. 로그인이 붙으면 계정과 사용자 기록이 생기므로, 그 전에 남용·유출 경로를 막는다.

## 범위와 방법
- **코드 읽기:** `api/`, `src/rate_limit.py`, `src/data_gaps.py`, `src/tools/places.py`, `web/`.
- **실제 요청:** 배포된 API에 입력 검증·접근 제어 요청을 보냈다. 대부분 모델 호출이 없다. 주소 위조 확인에만 짧은 질문 2개("hi")를 썼다.
- **설정:** 응답 헤더, CORS, 공개 문서 경로, Supabase 보안 권고(`get_advisors`), 의존성 취약점(`pip-audit`, `npm audit`).

## 찾은 문제와 조치

| # | 심각도 | 문제 | 근거 | 조치 |
| --- | --- | --- | --- | --- |
| 1 | **높음** | User-Agent에 `RagDogCheck`만 넣으면 질문 한도를 건너뜀 | `rate_limit.check`가 `data_gaps.from_check()`(User-Agent 비교)면 통과시켰다. User-Agent는 누구나 정한다 → 모델 호출 비용을 끝없이 쓸 수 있다 | 한도 면제는 비밀 토큰만: `X-RagDog-Check`가 `RAGDOG_CHECK_TOKEN`과 같을 때(`hmac.compare_digest`). 토큰을 정하지 않으면 면제가 없다. User-Agent는 데이터 공백 기록에서 빼는 데만 쓴다 |
| 2 | **높음** | `X-Forwarded-For`의 첫 값을 접속 주소로 써서, 네트워크 한도를 위조로 피함 | 가짜 주소 `203.0.113.9`로 두 번 → 같은 네트워크 해시, `198.51.100.7` → 다른 해시(`ragdog_rate_limit`에서 확인). 브라우저 id도 마음대로 바꿀 수 있어, 둘을 바꾸면 한도가 무력해진다 | 오른쪽에서 `RAGDOG_PROXY_HOPS`(기본 1)번째 값을 쓴다. 왼쪽 값은 요청자가 보낸 것이다. 배포 뒤 같은 방법으로 다시 확인한다(아래) |
| 3 | 중간 | 모델이 만든 SQL의 비용 제한 없음 | `validate_sql`은 모양(SELECT, place만)만 본다. `place`끼리 조인하면 수십억 행·수 분 → 서버를 붙잡는다(읽기 전용 연결이라 데이터 변경은 불가) | 쿼리마다 3초(`set_progress_handler`), 최대 1,000행(`fetchmany`) |
| 4 | 중간 | 웹 화면에 보안 헤더 없음 | 응답에 HSTS만 있고 CSP·클릭재킹 방지·nosniff가 없다. 로그인 뒤 XSS가 생기면 세션 토큰이 털린다 | CSP(스크립트·연결·이미지 출처 제한, `frame-ancestors 'none'`), `X-Frame-Options: DENY`, `nosniff`, `Referrer-Policy`, `Permissions-Policy`, `X-Powered-By` 제거 |
| 5 | 낮음 | API 문서(`/docs`, `/openapi.json`) 공개 | 모든 경로와 스키마가 보인다 | 배포에서는 끈다(`RAGDOG_API_DOCS=1`일 때만) |
| 6 | 낮음 | 피드백 저장을 브라우저 id만으로 셈 | id를 바꾸면 시간당 60건 제한을 피해 Supabase에 쓰레기 행을 쌓을 수 있다 | 네트워크당 시간 300건 상한을 더했다 |
| 7 | 낮음 | Python 의존성 취약 버전 | `urllib3 2.7.0`, `multidict 6.7.1`, `langgraph-sdk 0.4.2` | `2.8.0`, `6.9.1`, `0.4.7` |

## 받아들인 위험 (근거)
- **chromadb 1.5.9 (PYSEC-2026-311, 3813~3815):** Chroma **서버 HTTP API**의 코드 주입·권한 문제다. 우리는 서버 없이 앱 안에서 파일로만 쓴다(`PersistentClient`). 고친 버전이 나오면 올린다.
- **oauthlib 3.3.1 (PYSEC-2026-4114):** OAuth **서버**의 PKCE 비교 문제다. kubernetes 클라이언트를 거쳐 들어왔을 뿐 OAuth 서버를 돌리지 않는다.
- **Supabase `vector`·`pgroonga` 확장이 public 스키마에 있음(WARN):** 옮기면 검색 인덱스와 함수 참조를 다시 만들어야 한다. public 표는 모두 RLS가 켜져 있고 anon·authenticated 권한이 없다(ADR-0007). 그대로 둔다.
- **CSP의 `'unsafe-inline'`:** Next.js의 인라인 부트스트랩과 Leaflet 인라인 스타일 때문이다. nonce를 쓰면 모든 페이지가 동적 렌더링이 된다. 모델 답변은 react-markdown으로 그리며 HTML을 해석하지 않고, `javascript:` 링크는 막힌다.
- **브라우저 id 바꾸기:** 비로그인 사용자 구분의 한계다. 네트워크 한도(시간 60, 하루 200)가 받친다. 로그인 뒤에는 계정 id로 센다(P4).
- **지도 타일 요청:** OpenStreetMap에 보이는 지역(대략적 위치)이 전달된다. 위치 사용은 버튼을 누를 때만이다.

## 문제 없음을 확인한 것
- **입력 검증:** 1,001자 질문, 빈 질문, 깨진 JSON, 범위 밖 좌표, `top_k=9999`, 너무 큰 `limit`, SQL 흉내 시/도 이름, 경로 탐색은 모두 422/404로 막혔다. 오류에 내부 정보가 없다.
- **방문 준비 보고서:** 남의 멈춘 실행에 답하면 404다(소유자만, 한 번, 30분).
- **CORS:** 정식·미리보기·localhost만 허용하고, 다른 출처(`evil.vercel.app`)는 허용 헤더가 없다.
- **비밀값:** 화면 번들에 API 키·DB 주소가 없다. 모든 비밀은 Secret Manager에 있다.
- **SQLite:** 읽기 전용(`mode=ro`)으로 연다.

## 배포 뒤 확인할 것
1. **주소 위조:** 가짜 `X-Forwarded-For`를 다르게 넣은 두 요청이 같은 네트워크 해시가 되고, 위조 없는 요청과도 같아야 한다.
   - 값이 다르면 Cloud Run이 덧붙이는 값이 2개라는 뜻이다. `RAGDOG_PROXY_HOPS=2`로 바꾼다.
2. **API 문서:** `/docs`, `/openapi.json`이 404여야 한다.
3. **웹 헤더:** 응답 헤더를 확인하고, 홈 사진·지도 타일·API 호출이 CSP에 막히지 않는지 본다.

## 평가 스크립트에 미친 영향
- `scripts/evaluate_api.py`는 더 이상 User-Agent로 한도를 건너뛰지 않는다. 96문항을 한 번에 돌리려면 `RAGDOG_CHECK_TOKEN`이 필요하다.
  - 사용자가 Secret Manager에 만들고 API 배포에 연결한다. 토큰 값은 대화나 저장소에 남기지 않는다.
  - 토큰이 없으면 네트워크 한도(시간 60번)에 걸린다.
- 배포 확인(`check_deployed_app.py`, keep-alive)의 질문 1~2개는 이제 한도에 센다.

## P4(로그인) 뒤 점검 항목
- **OAuth:** PKCE 흐름인지, `redirectTo`가 허용 목록(정식·미리보기·localhost)에만 있는지 확인한다. 열린 리디렉션이 없어야 한다.
- **토큰 검증(API):** 서명·`aud`·`iss`·만료를 검증한다. `alg=none`, 다른 프로젝트 토큰, 만료 토큰은 거부해야 한다.
- **RLS:** 다른 사용자 JWT로 읽기·쓰기·지우기 → 0행이어야 한다. anon으로는 아무것도 안 돼야 한다. service_role 키는 화면에 없어야 한다.
- **세션:** 로그아웃하면 토큰과 화면 기록이 지워져야 한다. 공용 PC 시나리오, 토큰 저장 위치와 XSS 영향(CSP)을 본다.
- **기기 기록 옮기기:** 다른 사람 계정으로 섞이지 않아야 한다. 동의를 받은 뒤에만 옮긴다.
- **계정별 한도:** 로그인 사용자는 계정 id로 센다. 계정을 여러 개 만들어도 네트워크 한도가 받쳐야 한다.
- **개인정보:** 서버에 무엇을 저장하는지 안내한다. "내 기록 모두 지우기"가 서버 행까지 지워야 한다.
