# 운영 모니터링 (Langfuse)

2026-10-07부터 챗봇 실행마다 Langfuse 트레이스를 하나 남긴다. 구현은 `src/tracing.py`, 연결 지점은 `src/chat_graph.py`의 `run_chat()`.

## 무엇을 남기나

| 위치 | 내용 |
| --- | --- |
| 루트 span `chat`의 입력 | 질문의 SHA-256 앞 16자리와 글자 수 |
| 루트 span `chat`의 출력 | `output/chat_runs.jsonl`과 같은 실행 기록: 경로(route), CRAG 판정, 재작성 횟수, 보류 여부, 후보·채택 문서 ID, 모델별 토큰, 지연 |
| 하위 span (LangChain 콜백) | 그래프 노드(classify, health_retrieve, health_grade, …)와 모델 호출마다 시간, 모델 호출의 토큰·비용 |
| 세션 | 브라우저 세션의 무작위 ID를 한 번 더 해시한 값. 같은 탭의 질문들이 한 세션으로 묶인다 |
| 환경 | Streamlit Cloud(`/mount/src/…`)면 `production`, 그 외 `development`. `LANGFUSE_TRACING_ENVIRONMENT`로 바꿀 수 있다 |

## 답변 피드백 (2026-10-07)

- 이번 탭에서 받은 답변 아래에 👍/👎(`st.feedback`)를 보여 준다. 트레이싱이 켜져 있을 때만 보인다.
- 누르면 그 실행의 트레이스에 `user_feedback` BOOLEAN 점수(👍=1, 👎=0)가 붙는다.
- 점수 ID를 `<trace id>-user_feedback`으로 정해 두었다. 그래서 투표를 바꾸면 점수가 하나 더 생기지 않고 덮어써진다. 실제 프로젝트에서 👍 → 👎로 바꾼 뒤 조회해 점수 1개(False)만 남는 것을 확인했다.
- 보내는 값은 숫자 하나와 무작위 트레이스 ID뿐이다. 의견을 글로 받는 칸은 두지 않았다. 글을 받으면 서버에 사용자 텍스트가 남기 때문이다.
- 다시 연 예전 대화에는 버튼이 없다. 대화 기록에는 트레이스 ID를 저장하지 않는다.
- 대시보드에서는 Scores 메뉴나 트레이스 목록의 점수 열에서 경로(route) 태그와 함께 본다. 예: 근거 판정이 `incorrect`(보류)인 답변의 만족도.
- 점수를 읽을 때 새 조직은 `GET /api/public/v3/scores`(SDK: `client.api.scores_v3.get_many_v3`)를 쓴다. 예전 scores API는 막혀 있다.

## 개인정보: 텍스트는 서버를 떠나지 않는다

기존 원칙은 "서버에 대화 원문을 남기지 않는다"이다(대화는 브라우저에만 저장, 실행 로그는 질문 해시만). 트레이싱도 같은 원칙을 따른다.

- Langfuse SDK의 `mask` 훅(`mask_text`)이 SDK가 보내는 모든 입력·출력·메타데이터를 거친다.
- 숫자·참거짓·구조는 남기고, 문자열은 `[masked 32 chars]`처럼 길이만 남긴다.
- 예외는 `SAFE_KEYS`(route, decision, step, 문서 ID, 메시지 role, 모델 이름 등)에 해당하는 값뿐이다. 앱이 정한 값이거나 공개 데이터셋의 ID다.
- 그래서 질문, 답변, 반려견 프로필, 검색된 상담 본문, 대화 이력은 마스킹된다.

**검증:**

- `tests/test_tracing.py`가 실제 Langfuse 클라이언트에 메모리 내 exporter를 붙여 한 번 실행한 뒤, 보낼 span 전체에 질문·답변·문서의 단어(이름, 증상, 전화번호 형식)가 없는지 확인한다.
- 실제 프로젝트에도 질문 3개(건강·시설·보고서)를 보낸 뒤 v2 Observations API로 다시 읽었다. 23개 observation 중 질문 단어가 들어 있는 것은 0개였다(2026-10-07).

## 비용

- `langfuse` import로 메모리 약 11MB 증가(로컬 측정). 키가 없으면 import하지 않는다.
- 전송은 SDK의 백그라운드 스레드가 묶어서 보낸다. 답변 지연에는 영향이 없다.
- 트레이싱 설정·전송이 실패해도 답변은 그대로 나간다. 경고 로그만 남는다.

## 켜고 끄기

- `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`가 있으면 켜진다(`.env` 또는 Streamlit secrets). 주소는 `LANGFUSE_BASE_URL`.
- `LANGFUSE_TRACING_ENABLED=false`면 끈다.
- 테스트 실행 중에는 자동으로 꺼진다. `.env`에 실제 키가 있어도 테스트의 가짜 질문이 프로젝트에 쌓이지 않게 하기 위해서다.
  - 처음 통합할 때 이 처리가 없어서, 전체 테스트 1회분의 가짜 실행(마스킹됨, `development`)이 프로젝트에 들어갔다.

## 알아 둘 점

- **모델 이름:** Langfuse 콜백이 `ChatOpenAI`의 모델 이름을 `invocation_params.model_name`에서 찾는데, 지금 LangChain은 이 값을 주지 않는다. 그래서 generation의 model 칸이 비고 "not able to parse the LLM model" 경고가 찍힌다. 토큰·비용은 기록된다. 모델 이름은 메타데이터의 `ls_model_name`과 루트 span의 `token_usage`에 남는다.
- **조회 API:** 2026-09-16 이후 만든 Langfuse 조직은 예전 `GET /api/public/traces`를 쓸 수 없다(410). 데이터를 읽을 때는 `GET /api/public/v2/observations`(SDK: `client.api.observations.get_many`)를 쓴다.
