# 로그인(P4) 뒤 보안 점검 (2026-10-16)

[로그인 전 점검](2026-10-16-pre-login-review.md)의 "P4 뒤 점검 항목"을, P4-1~P4-4 배포 뒤 실제 서비스에 대해 확인했다. 실제 계정은 사용자가 직접 로그인했고, 공격 시험은 진짜 자격 증명 없이 위조 값으로만 했다.

## 결과 요약
| 영역 | 시험 | 결과 |
| --- | --- | --- |
| OAuth 흐름 | 실제 로그인 기록: authorize → Google → callback → `/token grant_type=pkce` 200 | ✅ PKCE로만 세션 발급 |
| 열린 리디렉션 | `redirect_to`에 `evil.example`, 미리보기 위장(`ragdog-evil-rndigkwks-projects.vercel.app`), 뒤에 붙이기(`…vercel.app.evil.example`), `//evil.example` | ✅ 모두 Site URL로 바뀜(`auth.flow_state.referrer`). 허용 목록(정식·localhost)만 그대로 |
| 화면의 돌아갈 경로 | `safeReturnPath`: `https://…`, `//…`, `/\…`, `javascript:`, `/auth/…` | ✅ 홈으로(단위 테스트) |
| API 토큰 검증 | 배포된 `GET /me`에 위조 토큰 7가지: 내 ES256 키+진짜 kid, 모르는 kid, `alg: none`, HS256(공개 JWK를 비밀로), HS256(publishable 키를 비밀로), 진짜 anon 키, 쓰레기 값 | ✅ 모두 `signed_in: false` |
| 토큰 조건 | 만료, 다른 aud·role·iss, sub 위조(서명 깨짐), uuid 아닌 sub | ✅ 거부(단위 테스트, 테스트 안에서 만든 ES256 키로 실제 서명) |
| RLS | 가짜 사용자 A·B로 읽기·쓰기·바꾸기·지우기·넘기기, 21번째 대화, 잘못된 id | ✅ 11가지 통과(`scripts/check_user_records.py`, 실제 DB에서 되돌림) |
| 공개 키로 직접 접근 | 로그인 없이 publishable 키로 사용자 표·앱 표 GET/POST/DELETE | ✅ 모두 `42501 permission denied` |
| 실제 계정 기록 | 옮기기·새 대화·반려견 정보 | ✅ 3행 모두 본인 `user_id`. 화면은 `user_id`를 보내지 않음(DB가 토큰에서 채움) |
| 세션 정리 | 로그아웃 → 토큰이 브라우저에서 지워지고 계정 기록이 화면에서 사라짐. 로그인 중에는 브라우저에 기록을 쓰지 않음 | ✅ Playwright |
| XSS 표면 | `dangerouslySetInnerHTML`·`innerHTML`·`eval` 없음. 답변은 react-markdown(HTML 해석 안 함). CSP로 스크립트·연결 출처 제한 | ✅ |

## 찾은 문제
| # | 심각도 | 문제 | 조치 |
| --- | --- | --- | --- |
| 1 | 중간 | **Supabase 이메일 가입이 켜져 있음.** Google만 쓰기로 했는데 `/auth/v1/settings`에 `email` 공급자가 켜져 있다(`disable_signup: false`). publishable 키만 있으면 누구나 이메일 가입을 요청할 수 있어, 우리 프로젝트 이름으로 남에게 확인 메일을 보내게 만들 수 있다. 확인 전에는 로그인되지 않는다(`mailer_autoconfirm: false`). Supabase 권고 "Leaked Password Protection Disabled"도 이 때문에 뜬다 | **사용자 작업:** Supabase → Authentication → Sign In / Providers → **Email 끄기**. Google 가입은 그대로 된다 |
| 2 | 낮음 | 계정 삭제 기능 없음 | **해결(같은 날):** service_role 키 없이 DB 함수 `delete_my_account()`(`scripts/sql/delete_my_account.sql`)로 지운다. 호출자 본인(`auth.uid()`)만 지울 수 있고, 세션·로그인 연결·기록은 cascade로 함께 지워진다. 테스트 8가지(남은 B는 그대로, anon·sub 없는 토큰·API 역할은 못 부름). 키를 두지 않은 이유: service_role은 RLS를 모두 건너뛰는 키라, API 하나가 뚫리면 프로젝트 전체가 뚫린다 |

## 받아들인 위험 (근거)
- **API CORS의 미리보기 정규식** (`^https://ragdog-[a-z0-9-]+-rndigkwks-projects\.vercel\.app$`): 다른 사람이 비슷한 이름의 Vercel 프로젝트를 만들 수 있다면 그 주소도 허용된다.
  - 하지만 CORS는 브라우저에서 우리 API를 부르는 것만 정한다. 그 사이트는 우리 화면의 토큰(우리 출처의 localStorage)을 읽을 수 없다.
  - API 호출 자체는 서버에서 CORS 없이도 할 수 있으므로 새로 열리는 것이 없다(한도는 네트워크·계정 기준).
  - 로그인 리디렉션 허용 목록에는 미리보기 와일드카드를 넣지 않았다(위 시험).
- **토큰을 localStorage에 둠:** supabase-js 기본값이다. XSS가 있으면 읽힌다. 대신 CSP, HTML 미해석, 위험 API 없음으로 XSS 자체를 막는다.
- **여러 Google 계정으로 한도 늘리기:** 계정마다 시간 10·하루 30번이다. 네트워크 한도(시간 60·하루 200)가 받친다.
- **세션 수명:** Supabase 기본값을 쓴다(access token 1시간, refresh token 회전). 비활성 만료 설정은 유료 플랜 기능이다.

## 사용자 확인으로 남은 것
- **계정 기준 한도의 실제 동작:** 로그인한 채 질문 1개 → 로그아웃하고 질문 1개를 하면, `ragdog_rate_limit`에서 두 질문의 사람 해시가 달라야 한다. 로그인 질문은 `user:<id>`, 로그아웃 질문은 브라우저 id다.
