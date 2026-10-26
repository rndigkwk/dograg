# 웹 앱 (Next.js, Vercel)

[구조 개요](README.md)의 한 부분입니다. 코드는 [`web/`](../../web), 측정 기록은 [web-frontend.md](../wiki/web-frontend.md), 결정은 [ADR-0008](../adr/0008-nextjs-frontend-fastapi-backend.md)에 있습니다.

| 항목 | 내용 |
| --- | --- |
| 스택 | Next.js 15(App Router), React 19, TypeScript, Tailwind CSS 4, Leaflet, supabase-js |
| 배포 | Vercel. PR마다 미리보기 주소, `main` 병합 시 운영 |
| 주소 | <https://ragdog-rndigkwks-projects.vercel.app> (검색 노출 없음: `*.vercel.app`은 `noindex`) |
| 테스트 | vitest(순수 로직), Playwright(가짜 API로 화면 흐름), 타입·린트·운영 빌드 (`web-ci.yml`) |

## 페이지

메뉴는 네 묶음입니다(`web/src/lib/nav.ts`). 데스크톱 메뉴와 휴대폰 아래 탭이 같은 표를 씁니다.

| 묶음 | 페이지 | 하는 일 | 부르는 API |
| --- | --- | --- | --- |
| 홈 | `/` | 질문창을 먼저 보여 주고 바로 상담으로 넘김 | `/health`(API 깨우기) |
| 상담 | `/chat` 질병 문의 | 답 스트리밍, 인용 번호와 근거, 응급 안내, 👍/👎, 상담 노트 저장 | `POST /chat`, `/feedback`, `/memory/note` |
| | `/visit-prep` 방문 준비 보고서 | 진행 단계 표시, 되묻기에 답하기, Word·txt 저장, 인쇄 | `POST /visit-prep`, `/answer`, `/retry` |
| | `/reports` 보고서 질문 | 보고서 5종 카드와 추천 질문, 쪽수 인용 답 | `POST /chat` (`route: "report"`, 분류 호출 없이 보고서 경로로) |
| 찾기 | `/places` 시설 찾기 | 종류·지역·현재 위치로 찾기, 지도 | `GET /places/*` |
| | `/fees` 지역별 진료비 | 시·도 점 그래프, 시·군·구 표 | `GET /fees/*` |
| 우리 아이 | `/care` 관리 일정 | 마지막 접종·구충·발톱 날짜로 다음 날짜 계산 (모델 없음) | 없음 |
| | `/memory` 상담 기억 | 저장한 상담 노트 보기·고치기·지우기 (로그인 필요) | 없음 (Supabase 직접) |
| 소개 | `/data` | 프로젝트 소개, 상담 통계, 시설 데이터, 출처 탭 | `GET /stats/overview` |

## 부품별 설명

### 1. 답 스트리밍 (`lib/sse.ts`, `lib/chat.ts`, `components/Chat.tsx`)

- **기능:** 답이 다 만들어지기 전에 글자를 보여 주고, 진행 단계("근거 확인 중")와 응급 안내를 답보다 먼저 보여 줍니다.
- **흐름:**
  1. 브라우저가 `fetch`로 `POST /chat`을 보냅니다. 본문은 질문, 최근 대화, 반려견 정보, (허용했으면) 위치입니다.
  2. 응답은 `event: <종류>\ndata: <json>` 형식의 조각입니다. `lib/sse.ts`가 조각을 잘라 이벤트로 바꿉니다.
  3. `lib/chat.ts`가 이벤트를 순서대로 화면 상태로 바꿉니다. 순수 함수라 브라우저 없이 시험합니다.
- **이벤트:** `urgent`(응급, 답보다 먼저), `step`(단계), `places`(시설 목록, 증상 답보다 먼저), `token`(답 글자), `evidence`(근거), `result`(경로·근거·trace id·레일 id), `limited`(질문 한도), `error`, `memory`(건강 답 뒤, 반려견 정보에 더할 만한 새 사실 제안).
- **선택한 이유:**
  - 질문 본문이 길고 대화와 프로필을 함께 보내야 해서 GET만 되는 `EventSource`를 쓸 수 없었습니다. 그래서 POST 응답을 직접 읽습니다.
  - Vercel 함수를 거치면 스트리밍 시간 제한과 비용이 붙습니다. 그래서 브라우저가 API를 직접 부르고, API는 CORS로 Vercel 주소만 허용합니다.
  - 증상 + 병원 질문은 병원 목록이 0.4초에 먼저 뜹니다(전에는 답이 끝나는 8초 뒤).

### 2. 로그인과 본인 기록 (`lib/supabase.ts`, `lib/records.ts`, `lib/store.ts`)

- **기능:** 로그인은 선택입니다. 로그인하지 않으면 대화와 반려견 정보를 이 브라우저(localStorage)에, 로그인하면 계정(Supabase 표)에 둡니다.
- **흐름:**
  - Google 로그인(Supabase Auth, PKCE)을 하면 브라우저가 사용자 토큰으로 Supabase 표 `ragdog_user_threads`, `ragdog_user_profile`, 상담 노트 표를 직접 읽고 씁니다.
  - 각 표는 RLS로 `user_id = auth.uid()`인 행만 허용합니다.
  - 로그인한 동안에는 브라우저에 새로 쓰지 않습니다. 공용 컴퓨터에서 로그아웃하면 사본이 남지 않습니다.
  - API에는 토큰을 보내지만, API는 질문 한도를 계정으로 세는 데만 씁니다([api.md](api.md) "질문 한도").
- **선택한 이유:**
  - 사용자 기록을 앱 코드가 아니라 DB 정책이 지키게 했습니다. API 계정(`ragdog_app`)은 사용자 표에 권한이 없어서, API 코드에 버그가 있어도 남의 기록이 샐 길이 없습니다([최소 권한](../security/least-privilege.md)).
  - 브라우저에 두는 공개 키(publishable key)는 공개용입니다. service_role 키는 어디에도 두지 않습니다.
  - localStorage에서 읽은 기록은 사람이 고쳤을 수 있어서, 레코드마다 검사하고 한도로 자릅니다(`lib/store.ts`).

### 3. 고정 자료 미리 받기 (`lib/prefetch.ts`)

- **기능:** 소개·시설·진료비 페이지의 표를 HTML에 넣어 보냅니다.
- **흐름:** 페이지의 서버 컴포넌트가 API에서 표를 받고, Vercel이 그 페이지를 하루 보관합니다(`revalidate = 86400`). 받기가 30초 안에 안 되면 예전처럼 브라우저가 받습니다.
- **선택한 이유:** 이 세 페이지의 LCP는 브라우저가 API를 기다리는 시간이었습니다. 자료는 하루에 한 번 바뀔까 말까 해서, 미리 넣어 LCP가 2.9~3.1초 → 2.0~2.4초가 됐습니다. 30초는 잠든 API가 깨는 시간(15~27초)을 넘기 위해서이고, 이 대기는 하루 한 번 다시 받을 때만 생깁니다.

### 4. 방문 준비 보고서 화면 (`lib/visitPrep.ts`, `components/VisitPrep.tsx`, `lib/reportFiles.ts`)

- **기능:** 상담 화면의 "이 상담으로 방문 준비 보고서 만들기"로 넘어와 보고서를 만들고, 팀이 되물으면 답하고, 결과를 파일로 저장합니다.
- **흐름:** 상담 내용은 URL이 아니라 sessionStorage로 넘깁니다. 실행이 멈추면(`paused`) 질문을 보여 주고 답을 `/answer`로 보내 같은 실행을 이어 갑니다. 실패하면 `/retry`로 끝낸 단계부터 다시 합니다.
- **선택한 이유:** 상담 글이 브라우저 기록과 서버 로그에 남지 않게 URL에 넣지 않았습니다. 보고서는 Markdown 그대로가 아니라 누구나 여는 txt와 Word(.docx)로도 줍니다.

### 5. 관리 일정 (`lib/careSchedule.ts`)

- **기능:** 접종·구충·발톱 손질 등 마지막 날짜를 넣으면 다음 날짜와 "지났어요 / 지금 할 때"를 보여 줍니다.
- **선택한 이유:** 주기는 공공 지침(동물사랑배움터 가이드라인 39~40쪽)의 값을 그대로 씁니다. 날짜 계산이라 모델이 필요 없고, 이 브라우저에만 둡니다.

### 6. 화면 무게와 접근성

- 마크다운 묶음은 답이 온 뒤에만 받습니다(`/chat` 첫 JS 232 → 188kB). 홈 사진은 화면 크기에 맞는 것만 받습니다(357 → 138KB).
- Lighthouse 모바일 9개 페이지 모두 접근성·모범 사례 100입니다. 채팅 화면의 흔들림(CLS)은 0.123 → 0.001입니다.
- 색 대비, 키보드 흐름, 선 아이콘(이모지 대신)을 맞췄습니다. 기록: [web-frontend.md](../wiki/web-frontend.md)

## 넣지 않은 것

| 후보 | 넣지 않은 이유 |
| --- | --- |
| Vercel 함수로 API 중계 | 스트리밍 시간 제한과 함수 사용량이 붙는다. 브라우저 → API 직접 + CORS로 충분 |
| Next 이미지 최적화 | Vercel 사용량이 들고, Unsplash가 이미 크기를 맞춰 준다 |
| 로그인 필수 | 건강 상담은 민감한 내용이라 로그인 없이도 쓰게 했다. 서버 저장은 로그인한 사람만 |

## 한계

- 로그인하지 않은 기록은 그 브라우저에만 있어서 다른 기기에서는 보이지 않습니다.
- 검색 노출이 없습니다(포트폴리오 프로젝트라 `noindex`를 유지합니다).
