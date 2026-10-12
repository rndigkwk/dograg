# 개선 기록: 측정 → 수정 → 검증

라그도그는 2026-09-28부터 10-12까지 PR 96개로 다듬었습니다. 이 문서는 그중 **문제를 숫자로 찾고, 고치고, 다시 재서 확인한** 사례를 모은 것입니다. 효과가 없어 **넣지 않은** 실험도 함께 남겼습니다. 기능별 설계와 이유는 [design.md](design.md)에, 실험의 자세한 기록은 [wiki/](wiki/)에 있습니다.

## 어떻게 쟀나

- **평가 세트를 먼저 쓴다.** 고칠 대상을 정하면, 고치기 전에 질문 세트와 기대 답을 먼저 쓰고 지금 코드로 잰다.
- **보고 고친 세트와 검증 세트를 나눈다.**
  - 규칙을 다듬을 때 본 세트(dev)는 성능이 실제보다 좋게 나온다.
  - 그래서 고치기 전에 따로 써 둔 세트(holdout, holdout2)로 다시 잰다.
  - 진료비 규칙은 dev에서 24/24였지만, 처음 보는 말투에서는 23/30이었다. 이 차이를 숨기지 않고 기록했다.
- **같은 질문끼리 비교한다.** 두 방식이 같은 질문에서 각각 맞히고 틀린 것을 세어 McNemar 검정을 한다. 예: 하이브리드 검색 p=0.016, 임베딩 미세조정 p=0.0001.
- **같은 날 함께 돌린다.** 모델 응답 시간은 날마다 흔들린다. 그래서 전후 코드를 같은 날 같은 상담으로 나란히 돌린다(예: #86, 상담 12개).
- **LLM 판정은 판정 자체의 흔들림을 잰다.** 같은 답을 두 번 판정한 일치율(86.5%, κ 0.79)을 기록하고, 그 안의 차이는 "개선"으로 말하지 않는다.
- **배포 앱에서 확인한다.** 병합 뒤 실제 브라우저로 배포 앱을 열어 본다. 이 과정에서 테스트로는 안 보이던 문제가 여러 번 나왔다(#83, #84, #47).

## 1. 검색 품질

| PR | 발견 | 측정 (전 → 후) | 무엇을 바꿨나 |
| --- | --- | --- | --- |
| [#1](https://github.com/rndigkwk/dograg/pull/1) | Dense 검색이 질문의 핵심 단어를 놓침 | 건강 hit@3 0.2264 → **0.2620** | Dense + BM25(Kiwi 명사) 하이브리드, RRF |
| [#40](https://github.com/rndigkwk/dograg/pull/40) | 질문에서 추론한 연령·진료과 필터가 기대는 라벨이 질문 본문과 34%·59%만 맞음 | hit@3 0.141 → **0.264** | 자동 필터 제거 (질문 줄이기는 효과 없어 미적용) |
| [#62](https://github.com/rndigkwk/dograg/pull/62) | 보고서 답변의 병목이 생성이 아니라 검색 | 기준 답과 맞는 답 23 → **30/36** (p=0.016) | 보고서 검색도 BM25 + Dense 하이브리드 |
| [#77](https://github.com/rndigkwk/dograg/pull/77) [#78](https://github.com/rndigkwk/dograg/pull/78) | 상담 글은 길고 사용자 질문은 짧아 임베딩이 약함 | 짧은 질문 useful@3 0.600 → **0.783** (p=0.0001), 긴 질문 0.72 → **0.84** (p=0.023) | 보호자 말투 합성 질의($3.37)로 ko-sroberta 미세조정(Colab T4 4.6분), ONNX int8 |
| [#96](https://github.com/rndigkwk/dograg/pull/96) | 배포 앱에서 진료비·시설 질문 뒤의 건강 질문이 "자료에 없다" | holdout 주제 전환 0.38 → **1.0**, 시설 지역 4/6 → **6/6** (이어받기 0.72 → 0.64) | 앞선 질문을 모두 붙이지 않고, 모델이 혼자 읽히는 검색어를 씀 |
| [#88](https://github.com/rndigkwk/dograg/pull/88) | 기본 관리 질문(복용 주기, 목욕 주기)을 보류함 | 30개 중 핵심 답함 20, 못 줌 7 (7개 중 5개는 자료 구성 문제) | 측정만. 후보 5 → 8도 20/3/7로 같아 바꾸지 않음 |
| [#98](https://github.com/rndigkwk/dograg/pull/98) | "24시 하는 곳은?"처럼 시설 단어 없는 후속 질문이 다음 건강 검색의 맥락에 들어감 (#96에서 남긴 것) | 앞선 건강 질문 목록 0/30 → **30/30**, 검색어 오염 1/30 → **0/30**, 재작성 호출 10 → **4**/10문항 | 답변마다 기록된 경로로 건강 질문만 맥락에 씀 |

## 2. 근거와 안전

| PR | 발견 | 측정 (전 → 후) | 무엇을 바꿨나 |
| --- | --- | --- | --- |
| [#3](https://github.com/rndigkwk/dograg/pull/3) [#5](https://github.com/rndigkwk/dograg/pull/5) | 근거 없는 질문에도 그럴듯하게 답함 | 근거 없는 질문 보류 0 → **16/20**. v2에서 과잉 보류 3/17 → 1/19, 토큰 절반 | CRAG(근거 평가 → 재검색 → 보류), 건강 상담에만 적용 |
| [#10](https://github.com/rndigkwk/dograg/pull/10) [#11](https://github.com/rndigkwk/dograg/pull/11) | 답변에 근거 밖 의학 사실(검사 이름 등)이 섞임 | 건강 답변 충실도 0.79 → **0.94**, 근거 밖 의학 사실 → 0 | 답변 프롬프트에 근거만 쓰는 규칙 |
| [#34](https://github.com/rndigkwk/dograg/pull/34) | 답할 질문을 보류(h06·h09) | 과잉 보류 2/38 → **1/38**, accuracy 0.883 → 0.900 | 재검색 때 진료과 필터를 풂 |
| [#27](https://github.com/rndigkwk/dograg/pull/27) | 응급 질문에 답변이 먼저 나옴 | – | 응급 신호가 보이면 답변 전에 가까운 병원부터 |
| [#70](https://github.com/rndigkwk/dograg/pull/70) | 응급 규칙이 "청색증", "위 확장" 등을 놓침 | 응급 9/40 → **29/40**, 오탐 9 → **0** | 평가셋(dev/holdout) + 규칙 보강 |
| [#73](https://github.com/rndigkwk/dograg/pull/73) | 규칙이 처음 보는 표현을 놓침 | holdout2 1/20 → **19/20**, 오탐 0. 실제 질문 경고율 32.5%(2택) → **9%**(3택) | 규칙이 놓친 질문만 OpenAI Decisions 3택(지금 응급/곧 진료/아님) |
| [#99](https://github.com/rndigkwk/dograg/pull/99) | 답의 일부가 자료에 있어도 "검색된 자료에는 … 없습니다"로 시작함 (#11 규칙의 대가) | 첫 문장이 "자료에 없다": 답할 수 있는 건강 8 → **2**/20, 기본 관리 7·5 → **3·2**/30. 답하면 안 되는 질문은 20/20 그대로, 충실도 하락 없음 | 답이 되는 내용을 먼저, 없는 부분은 바로 뒤에 |
| [#101](https://github.com/rndigkwk/dograg/pull/101) | 배포 앱 답이 다른 보호자의 상담(내일 MRI)을 "앞서 ~하셨으니"로 이 보호자의 병력처럼 씀 | 근거 1건 문항에서 귀속 15/90 → **0/90**, 보호자가 실제로 말한 병력 짚기 12/12 유지, 충실도 하락 없음 | 근거에 "다른 보호자의 질문" 표시, 사례를 보호자 이야기로 쓰지 않는 규칙 |
| [#102](https://github.com/rndigkwk/dograg/pull/102) | 답을 기다리다 새 질문을 보내면 첫 질문이 답 없이 남음 (Cloud Run 확인 중 발견) | 첫 질문에 답이 붙음 0/3 → **3/3**, 질문 하나 답 시간 늘지 않음 (중앙값 6.1 → 5.1초) | 답하는 동안 입력창을 닫음 |
| [#103](https://github.com/rndigkwk/dograg/pull/103) | 가드레일 현재 상태 (수업 전 기준선) | 사람 약 용량 16/16·탈옥 8/8 안전, 주입 10/16, **범위 밖 요청 0/16**, **개인정보 OpenAI로 나감 16/16**, 정상 질문 15/16 | 측정만. 원인: 일반 대화 프롬프트에 범위 없음, 전송 전 마스킹 없음 |
| [#106](https://github.com/rndigkwk/dograg/pull/106) | 일반 대화 노드가 "저는 ChatGPT예요"·코딩·번역을 말하고 범위 밖 요청을 수행 (배포 질문의 3%) | 범위 밖 요청 거절 0/16 → **8/8**, 기능 문의 0/6 → **6/6**, 인사 0/6 → **6/6**, 응답 2.0 → 0.3초 | 모델 호출을 없애고 종류별 고정 문구 |

## 3. 진료비와 시설

| PR | 발견 | 측정 (전 → 후) | 무엇을 바꿨나 |
| --- | --- | --- | --- |
| [#82](https://github.com/rndigkwk/dograg/pull/82) | 진료비 질문에 답할 자료가 없음 | 수집 6,413행, 보도자료 전국값과 **4개 값 모두 일치** | 정부 진료비 조사 수집, 모델 없이 표 그대로 답 |
| [#85](https://github.com/rndigkwk/dograg/pull/85) | dev 24/24였지만 처음 보는 말투에서 약함 | holdout 23/30, 오분류 6/20 → 고친 뒤 holdout2 17 → **20/20**, 오분류 9 → **2/15** | "얼마나 자주"는 비용 질문 아님, 몇만원·키로·일산 등 |
| [#85](https://github.com/rndigkwk/dograg/pull/85) | 방문 보고서가 해운대구 상담에 대구광역시 진료비 인용 | 지역 일치 4/5 → **3/3** | "해운대구" 안의 "대구"를 시·도로 읽지 않음 |
| [#72](https://github.com/rndigkwk/dograg/pull/72) | "수원 동물병원"을 모델이 SQL로 처리(4~9초), 3/14 지역 놓침 | 지역 이름 16/16, 모델 호출 0 | 짧은 지역 이름 사전 |
| [#69](https://github.com/rndigkwk/dograg/pull/69) | "설사하는데 마포구 병원 어디?"에서 병원 목록이 답변 뒤에 나옴 | 병원 목록 표시 **0.38초** | 목록 먼저, 증상 답변은 아래에 |
| [#95](https://github.com/rndigkwk/dograg/pull/95) | "3곳 알려줘"에 10곳 (컨테이너 측정 중 발견) | 개수 평가 11/18 → **18/18** | "만" 없는 개수, 한글 수사 |

## 4. 방문 준비 보고서 (멀티에이전트 팀)

| PR | 발견 | 측정 (전 → 후) | 무엇을 바꿨나 |
| --- | --- | --- | --- |
| [#42](https://github.com/rndigkwk/dograg/pull/42) | 작성자가 얻을 수 없는 정보를 계속 요청해 반복 상한에 걸림 | 검수 통과율 0.70 → **1.00**, 시간 p50 68 → **49초**, 사람 확인 5/12 → 0 | 추가 조사는 한 번, 검수 추론 강도 low |
| [#47](https://github.com/rndigkwk/dograg/pull/47) | 재부팅 직후 증상 조사가 모두 실패 (배포 앱 trace) | 실패 → 정상 | 검색 자원을 조사 스레드가 아닌 페이지 스레드에서 먼저 로드 |
| [#53](https://github.com/rndigkwk/dograg/pull/53) | 통과한 보고서도 안에서 반복했을 수 있음 | 반복 의심 2/12, 기준 0.34 넘으면 실패 | 노드 방문 횟수 기록, 정기 평가에서 감시 |
| [#86](https://github.com/rndigkwk/dograg/pull/86) | #82 뒤 보고서 품질을 실제로 재지 않았음 | 지역 통계 인용 0/2 → **2/2**, 금액 표와 일치 2/2 | 같은 날 전후 비교 + 진료비 인용 지표 |
| [#93](https://github.com/rndigkwk/dograg/pull/93) | 조사원이 결과를 받아 놓고 답 없이 끝남 | 응답이 추론 조각 101개에서 잘림. 이어서 다시 물으면 6/13 → 새 요청으로 묻기 **15/15** | 도구 결과만 넣어 새로 묻기 |
| [#87](https://github.com/rndigkwk/dograg/pull/87) | 다시 묻는 순간 문제가 가려짐 | `reask_rate` ≤ 0.25, `no_answer_rate` ≤ 0.09 | 정기 평가 기준 추가 |

## 5. 속도와 배포

| PR | 발견 | 측정 (전 → 후) | 무엇을 바꿨나 |
| --- | --- | --- | --- |
| [#6](https://github.com/rndigkwk/dograg/pull/6) | 첫 건강 질문 대기 약 165초 (BM25 색인 구축) | 165초 → **8초** | BM25 토큰 캐시 + 워밍업 |
| [#7](https://github.com/rndigkwk/dograg/pull/7) [#14](https://github.com/rndigkwk/dograg/pull/14) | 무료 배포에서 메모리 초과 경고 | 최대 메모리 1,817 → **985MB** | 네이티브 스레드 제한, 질문 임베딩을 ONNX int8로, torch 제외 |
| [#32](https://github.com/rndigkwk/dograg/pull/32) | 근거 평가가 느림 | 건강 답변 첫 글자 9.1 → **6.0초** | 근거 평가 추론 끄기 |
| [#60](https://github.com/rndigkwk/dograg/pull/60) | 규칙으로 못 정한 질문의 라우팅이 느림 | 1.4 → **0.36초**, 정확도 같음 | OpenAI Decisions(분류 API) |
| [#71](https://github.com/rndigkwk/dograg/pull/71) | 리부트를 빠뜨려 챗봇 페이지가 ImportError인데 점검은 성공 | – | 모든 페이지와 챗봇 응답까지 확인, 병합 직후에도 실행 |
| [#89](https://github.com/rndigkwk/dograg/pull/89)~[#91](https://github.com/rndigkwk/dograg/pull/91) | 무료 호스팅의 잠자기, 리소스 한계 | 최고 메모리 1.06GiB/2GiB, 꺼진 상태 첫 화면 **23초**, 배포 약 3분 | Cloud Run 이원화. [docker-deployment.md](docker-deployment.md) |

## 6. 배포 앱에서 직접 확인하다 찾은 버그

| PR | 증상 | 원인 | 확인 |
| --- | --- | --- | --- |
| [#83](https://github.com/rndigkwk/dograg/pull/83) | 진료비 답변이 대화 저장 단계에서 오류 | 저장 모델의 경로 목록에 `fee`가 없음 | 그래프의 모든 경로를 저장해 보는 테스트 추가 |
| [#84](https://github.com/rndigkwk/dograg/pull/84) | "15,000~110,000원"의 물결표가 사라지고 취소선이 그어짐 | Streamlit Markdown이 `~` 두 개를 취소선으로 읽음 | 화면 출력에서만 이스케이프, 내려받기 파일은 원문 |
| [#51](https://github.com/rndigkwk/dograg/pull/51) | 새 대화 첫 답변의 보고서 버튼이 배포 앱에서만 무시됨 | 대화 ID가 저장 단계에서 생겨, 버튼 키가 `None` → ID로 바뀜. 배포 앱은 저장·재실행이 몇 초 걸려 그 사이 클릭이 사라진 버튼에 감 | 저장을 먼저 해 ID를 확정한 뒤 버튼을 그림 |
| [#24](https://github.com/rndigkwk/dograg/pull/24) | 재부팅 직후 `/rag` 링크가 메뉴·대화 기록 없이 열림 | `pages/` 폴더가 있으면 Streamlit이 첫 실행 전까지 예전 멀티페이지 방식으로 그 파일을 바로 실행 | 페이지 폴더를 `app_pages/`로 옮김 |
| [#66](https://github.com/rndigkwk/dograg/pull/66) | 배포 로그의 `StopException`, 워밍업 스레드가 죽어 자원이 첫 질문 때 올라감 | 워밍업 스레드가 부른 로더에 스피너가 있었고, 화면이 다시 그려지면 그 스레드 안에서 예외 | 로더의 스피너 제거 (#47과 같은 뿌리) |

## 7. 효과가 없어 넣지 않은 실험

넣지 않은 이유도 숫자로 남겼습니다. "해 봤는데 안 됐다"는 같은 시도를 반복하지 않게 해 줍니다.

| PR | 시도 | 결과 | 결정 |
| --- | --- | --- | --- |
| [#13](https://github.com/rndigkwk/dograg/pull/13) | CRAG 근거 평가 순서로 다시 정렬(리랭커 대용, 100문항) | 지금 후보 수에서는 hit@3 개선 없음 | 미적용 |
| [#50](https://github.com/rndigkwk/dograg/pull/50) | ONNX 리랭커 3종, 보고서를 페이지 단위로 답하기 | 리랭커: 상업 사용 가능한 두 모델은 useful@3 0.72 → 0.69·0.45로 오히려 나쁨, 나은 하나(0.76)는 비상업 라이선스·8초·0.5GB. 페이지 단위: 25 → 23/36 | 미적용 |
| [#52](https://github.com/rndigkwk/dograg/pull/52) | Qwen3-Reranker-0.6B (ONNX, 교안 리랭커) | 품질 같음, 질문당 **166초** | 미적용 |
| [#56](https://github.com/rndigkwk/dograg/pull/56) | 보고서 답변 컨텍스트 압축 (day48) | 정답 23 → 24·25/36(p=1.0·0.69, 실행 간 흔들림 2문항 안), 답까지 2.7 → 4.3초 | 미적용 |
| [#64](https://github.com/rndigkwk/dograg/pull/64) | 챗봇 Self-RAG (day53) | 충실도 0.927 → 0.941(판정 흔들림 안), 시간 p50 8.5 → **16.1초** | 기본 꺼짐 (설정으로 켤 수 있음) |
| [#40](https://github.com/rndigkwk/dograg/pull/40) | 긴 질문을 줄여 검색 | 효과 없음 | 미적용 (필터 제거만 적용) |
| [#88](https://github.com/rndigkwk/dograg/pull/88) | CRAG 검색 후보 5 → 8 | 기본 관리 20/3/7 그대로, 토큰 +19~24% | 5 유지 |

## 8. 측정 방법 자체를 고친 경우

평가 지표가 틀리면 개선도 틀립니다. 지표를 의심해서 고친 경우입니다.

- **라벨 기반 정답 → "쓸모" 판정 (#50):** 정답 규칙이 기대는 라벨이 질문과 맞지 않아(#40에서 발견), 근거가 실제로 쓸모 있는지 LLM으로 판정하는 `useful@3`로 바꿨다. 판정 일치율도 함께 쟀다.
- **진료비 인용 지표의 빈틈 (#85, #86):** 처음 만든 "금액 일치" 지표가 해운대구 보고서의 대구 진료비 인용을 정답으로 셌다. 인용한 행과 금액이 서로 맞았기 때문이다. 그래서 "지역 일치" 지표를 더했다.
- **채점기 라벨 보정 (#85):** 구 값이 없을 때 앱이 시·도 값으로 답하는 경우를 채점기가 오답으로 셌다. 앱이 맞았다. 고치기 전 숫자도 보정한 채점기로 다시 쟀다.
- **실패 사유 오기 (#86):** API의 미완료 응답을 코드가 "호출 상한"으로 기록하고 있었다. 사유를 바로 적게 고쳐서 #93의 원인 조사가 가능해졌다.

## 전체 PR 목록

| # | 날짜 | 제목 |
| ---: | --- | --- |
| [1](https://github.com/rndigkwk/dograg/pull/1) | 2026-09-28 | feat: enable hybrid health retrieval |
| [2](https://github.com/rndigkwk/dograg/pull/2) | 2026-10-03 | Feat/report OpenAI embeddings |
| [3](https://github.com/rndigkwk/dograg/pull/3) | 2026-10-04 | Feat/crag langgraph |
| [4](https://github.com/rndigkwk/dograg/pull/4) | 2026-10-04 | Fix/router conflicts |
| [5](https://github.com/rndigkwk/dograg/pull/5) | 2026-10-04 | feat: CRAG v2 — 건강 상담에만 적용, 판정 완화와 재평가 |
| [6](https://github.com/rndigkwk/dograg/pull/6) | 2026-10-04 | perf: 첫 건강 질문 대기 시간 약 165초 → 8초 (BM25 토큰 캐시 + 워밍업) |
| [7](https://github.com/rndigkwk/dograg/pull/7) | 2026-10-04 | perf: cut memory after the Streamlit memory-limit warning |
| [8](https://github.com/rndigkwk/dograg/pull/8) | 2026-10-05 | docs: restructure README as a portfolio page |
| [9](https://github.com/rndigkwk/dograg/pull/9) | 2026-10-05 | feat: stream answers and show the current step while waiting |
| [10](https://github.com/rndigkwk/dograg/pull/10) | 2026-10-05 | eval: answer faithfulness - are claims backed by the evidence? |
| [11](https://github.com/rndigkwk/dograg/pull/11) | 2026-10-05 | feat: ground health answers - facts only from evidence |
| [12](https://github.com/rndigkwk/dograg/pull/12) | 2026-10-05 | feat: ground health answers - facts only from evidence (land #11 on main) |
| [13](https://github.com/rndigkwk/dograg/pull/13) | 2026-10-05 | eval: CRAG grader as a reranker - no gain at the current pool size |
| [14](https://github.com/rndigkwk/dograg/pull/14) | 2026-10-05 | perf: embed health questions with ONNX Runtime and keep torch out of the app |
| [15](https://github.com/rndigkwk/dograg/pull/15) | 2026-10-06 | docs: design for tool modules, browser-stored conversations and pet profile |
| [16](https://github.com/rndigkwk/dograg/pull/16) | 2026-10-06 | refactor: split chat tools out of pages/rag.py into src/tools (phase 1) |
| [17](https://github.com/rndigkwk/dograg/pull/17) | 2026-10-06 | feat: storage layer for browser-kept conversations and the pet profile (phase 2) |
| [18](https://github.com/rndigkwk/dograg/pull/18) | 2026-10-06 | feat: keep conversations in the browser, with a thread list and clear button (phase 3) |
| [19](https://github.com/rndigkwk/dograg/pull/19) | 2026-10-06 | feat: history on every page, and the pet profile as long-term memory (phase 4) |
| [20](https://github.com/rndigkwk/dograg/pull/20) | 2026-10-06 | fix: save the storage notice flag on every page |
| [21](https://github.com/rndigkwk/dograg/pull/21) | 2026-10-07 | feat: 반려동물 시설 DB — 공공데이터 6종, 38,529곳 |
| [22](https://github.com/rndigkwk/dograg/pull/22) | 2026-10-07 | fix: 시설 검색에서 이전 질문의 개수 조건이 따라오는 문제 |
| [23](https://github.com/rndigkwk/dograg/pull/23) | 2026-10-07 | feat: Langfuse 운영 모니터링 (텍스트 마스킹) |
| [24](https://github.com/rndigkwk/dograg/pull/24) | 2026-10-07 | fix: 재부팅 직후 딥링크(/rag 등)가 메뉴 없이 열리는 문제 |
| [25](https://github.com/rndigkwk/dograg/pull/25) | 2026-10-07 | fix: 시설 전화번호를 하이픈 형식으로 통일 |
| [26](https://github.com/rndigkwk/dograg/pull/26) | 2026-10-07 | feat: 답변 피드백(👍/👎)을 Langfuse 점수로 기록 |
| [27](https://github.com/rndigkwk/dograg/pull/27) | 2026-10-07 | feat: 응급 신호가 보이면 가까운 동물병원을 답변보다 먼저 표시 |
| [28](https://github.com/rndigkwk/dograg/pull/28) | 2026-10-07 | eval: 시설 검색 라우팅 평가 세트(36문항)와 놓친 건강 표현 보강 |
| [29](https://github.com/rndigkwk/dograg/pull/29) | 2026-10-07 | docs: 구조도와 README에 시설 검색·응급 안내·Langfuse 반영 |
| [30](https://github.com/rndigkwk/dograg/pull/30) | 2026-10-07 | docs: Langfuse 대시보드 캡처를 README와 모니터링 위키에 추가 |
| [31](https://github.com/rndigkwk/dograg/pull/31) | 2026-10-07 | fix: 답변 중 화면이 다시 실행돼도 답변을 마저 완성 |
| [32](https://github.com/rndigkwk/dograg/pull/32) | 2026-10-07 | perf: 근거 평가에서 추론 끄기 — 건강 답변 첫 글자 9.1초 → 6.0초 |
| [33](https://github.com/rndigkwk/dograg/pull/33) | 2026-10-07 | eval: 평가 세트를 Langfuse 데이터셋·실험으로 운영 |
| [34](https://github.com/rndigkwk/dograg/pull/34) | 2026-10-07 | fix: 재검색 때 진료과 필터를 풀어 과잉 보류(h06·h09) 해결 |
| [35](https://github.com/rndigkwk/dograg/pull/35) | 2026-10-07 | feat: 멀티에이전트 팀 — 병원 방문 준비 보고서 (day55 과제 B) |
| [36](https://github.com/rndigkwk/dograg/pull/36) | 2026-10-07 | chore: 로컬 실행은 벡터 DB 복사본을 열어 chroma.sqlite3를 바꾸지 않음 |
| [37](https://github.com/rndigkwk/dograg/pull/37) | 2026-10-07 | docs: Langfuse 모델 이름이 비어 보이는 문제 — 현재는 기록됨을 확인하고 문서 정정 |
| [38](https://github.com/rndigkwk/dograg/pull/38) | 2026-10-07 | chore: 배포 앱이 잠들지 않게 8시간마다 헤드리스 브라우저로 방문 |
| [39](https://github.com/rndigkwk/dograg/pull/39) | 2026-10-07 | feat: 방문 준비 보고서 페이지(실행 제한) + 상담 12개 Langfuse 실험 |
| [40](https://github.com/rndigkwk/dograg/pull/40) | 2026-10-07 | fix: 건강 검색에서 자동 필터를 빼 hit@3 0.141 → 0.264 (질문 줄이기는 효과 없어 미적용) |
| [41](https://github.com/rndigkwk/dograg/pull/41) | 2026-10-07 | ci: 매주 회귀 평가 자동화 (CRAG 60 + 라우팅 36, 기준 넘으면 실패) |
| [42](https://github.com/rndigkwk/dograg/pull/42) | 2026-10-07 | perf: 방문 준비 팀 반복 줄이기 + 가벼운 검수 — 통과율 0.70→1.00, p50 68→49초 |
| [43](https://github.com/rndigkwk/dograg/pull/43) | 2026-10-08 | merge: 방문 준비 보고서 페이지(#39)와 팀 속도 개선(#42)을 main에 반영 |
| [44](https://github.com/rndigkwk/dograg/pull/44) | 2026-10-08 | test: CI 실패 수정 — 팀 테스트가 API 키 없이도 돌도록 검수 모델도 가짜로 교체 |
| [45](https://github.com/rndigkwk/dograg/pull/45) | 2026-10-08 | feat: 방문 보고서 근거를 ①② 번호로, 질병 문의의 보고서 근거는 2~3줄 + 자세히 보기 |
| [46](https://github.com/rndigkwk/dograg/pull/46) | 2026-10-08 | feat: 방문 준비 팀 실패 처리 + Langfuse 운영 설정 (day56 적용) |
| [47](https://github.com/rndigkwk/dograg/pull/47) | 2026-10-08 | fix: 재부팅 직후 방문 보고서의 증상 조사가 모두 실패하던 문제 (검색 자원을 페이지 스레드에서 먼저 로드) |
| [48](https://github.com/rndigkwk/dograg/pull/48) | 2026-10-08 | feat: 건강 답변 아래 '이 상담으로 방문 준비 보고서 만들기' 버튼 |
| [49](https://github.com/rndigkwk/dograg/pull/49) | 2026-10-08 | docs: README 맨 위 1분 요약, 팀 상세는 위키로 |
| [50](https://github.com/rndigkwk/dograg/pull/50) | 2026-10-08 | eval: 라벨 대신 '쓸모'로 판정한 검색 평가 세트 + 리랭커·페이지 단위 답변 실험 (둘 다 미적용) |
| [51](https://github.com/rndigkwk/dograg/pull/51) | 2026-10-08 | fix: 새 대화 첫 답변의 '방문 준비 보고서 만들기' 버튼 클릭이 배포 앱에서 무시되던 문제 |
| [52](https://github.com/rndigkwk/dograg/pull/52) | 2026-10-08 | eval: 교안 리랭커 Qwen3-Reranker-0.6B(ONNX) 측정 — 품질 동일, 질문당 166초로 미적용 |
| [53](https://github.com/rndigkwk/dograg/pull/53) | 2026-10-08 | 방문 준비 팀: 노드 방문 횟수 기록 + 정기 평가에서 반복 감시 (day56 과제 1) |
| [54](https://github.com/rndigkwk/dograg/pull/54) | 2026-10-08 | 방문 준비 팀: 진료비 조사 실패 시 기본 안내로 채우기 (day56 과제 2 폴백) |
| [55](https://github.com/rndigkwk/dograg/pull/55) | 2026-10-08 | 방문 준비 팀: 계획 전에 보호자에게 되묻기 (day51 interrupt) |
| [56](https://github.com/rndigkwk/dograg/pull/56) | 2026-10-08 | 실험 12: 보고서 답변 컨텍스트 압축 (day48) — 미적용, 평가와 기록 |
| [57](https://github.com/rndigkwk/dograg/pull/57) | 2026-10-08 | 챗봇: 긴 대화 요약 기억 (day52) + 답변 보류 안내 (day53) |
| [58](https://github.com/rndigkwk/dograg/pull/58) | 2026-10-08 | README: #53~#57 기능을 1분 요약·지표·데모에 반영 |
| [59](https://github.com/rndigkwk/dograg/pull/59) | 2026-10-08 | 작은 정리: 보류 답변엔 보고서 버튼 숨김, 멈춘 보고서 30분 만료, README 필터 문구 |
| [60](https://github.com/rndigkwk/dograg/pull/60) | 2026-10-08 | 라우터 폴백을 OpenAI Decisions(HTTP)로: 폴백 질문 1.4초 → 0.36초, 정확도 동일 |
| [61](https://github.com/rndigkwk/dograg/pull/61) | 2026-10-08 | 긴 대화: 요약 속 지병을 건강 검색어에 반영 (day52) |
| [62](https://github.com/rndigkwk/dograg/pull/62) | 2026-10-08 | 보고서 검색을 BM25 + Dense 하이브리드로 (실험 13: 정답 23 → 30/36) |
| [63](https://github.com/rndigkwk/dograg/pull/63) | 2026-10-08 | 증상 + 병원 찾기 질문에 두 답을 함께 (day54) + '24시간' 병원 거르기 |
| [64](https://github.com/rndigkwk/dograg/pull/64) | 2026-10-08 | 실험: 챗봇 Self-RAG (day53) — 충실도 차이 없음, 시간 2배라 기본 꺼짐 |
| [65](https://github.com/rndigkwk/dograg/pull/65) | 2026-10-08 | 위키: 교안 Day 46~56 적용·테스트·미적용 정리 |
| [66](https://github.com/rndigkwk/dograg/pull/66) | 2026-10-08 | 배포 로그의 StopException: 워밍업 스레드가 스피너 때문에 죽던 문제 |
| [67](https://github.com/rndigkwk/dograg/pull/67) | 2026-10-08 | README: 10-09 작업 반영 (보고서 하이브리드, 복합 질문, 라우터, Self-RAG, 교안 정리) |
| [68](https://github.com/rndigkwk/dograg/pull/68) | 2026-10-09 | README 아키텍처 그림과 프로젝트 구조를 지금 코드에 맞춤 |
| [69](https://github.com/rndigkwk/dograg/pull/69) | 2026-10-09 | 복합 질문: 병원 목록을 먼저 보여 주기 (0.38초) |
| [70](https://github.com/rndigkwk/dograg/pull/70) | 2026-10-09 | 응급 신호 감지 평가셋 + 규칙 보강 (응급 9/40 → 29/40, 오탐 9 → 0) |
| [71](https://github.com/rndigkwk/dograg/pull/71) | 2026-10-09 | 배포 앱 점검: 모든 페이지 오류 확인 + 챗봇 응답 확인, 병합 직후에도 실행 |
| [72](https://github.com/rndigkwk/dograg/pull/72) | 2026-10-09 | 시설 검색: 짧은 지역 이름(수원·부산·강남) 인식 + 동반 시설 카테고리 거르기 |
| [73](https://github.com/rndigkwk/dograg/pull/73) | 2026-10-09 | 응급 감지: 규칙이 놓친 질문에 OpenAI Decisions 두 번째 판단 (holdout2 1/20 → 19/20) |
| [74](https://github.com/rndigkwk/dograg/pull/74) | 2026-10-09 | 배포 앱 점검 중복 실행 방지 + README 테스트 수 갱신 |
| [75](https://github.com/rndigkwk/dograg/pull/75) | 2026-10-09 | README 다이어트 + 과제 검사용 절(멀티에이전트 요구사항, 교안 Day별 표) |
| [76](https://github.com/rndigkwk/dograg/pull/76) | 2026-10-09 | AI Hub 데이터·보고서 PDF를 공개 저장소에서 분리 (비공개 HF 데이터셋) |
| [77](https://github.com/rndigkwk/dograg/pull/77) | 2026-10-09 | 건강 검색 임베딩 미세조정: 짧은 질문 useful@3 0.625 → 0.800 (실험 기록, 앱 적용 전) |
| [78](https://github.com/rndigkwk/dograg/pull/78) | 2026-10-09 | 미세조정 임베딩 모델 앱 적용: 짧은 질문 useful@3 0.600 → 0.783 (앱 경로) |
| [79](https://github.com/rndigkwk/dograg/pull/79) | 2026-10-09 | 문서 정리: 내부 작업 노트는 빼고 발표 자료는 docs로 |
| [80](https://github.com/rndigkwk/dograg/pull/80) | 2026-10-09 | 안 쓰는 파일·의존성 정리 |
| [81](https://github.com/rndigkwk/dograg/pull/81) | 2026-10-09 | sentence-transformers·torch를 스크립트 전용 그룹으로 (배포 설치에서 제외) |
| [82](https://github.com/rndigkwk/dograg/pull/82) | 2026-10-10 | 지역별 진료비: 정부 조사 통계로 챗봇 답변 + 방문 보고서 진료비 근거 |
| [83](https://github.com/rndigkwk/dograg/pull/83) | 2026-10-10 | 핫픽스: 진료비 답변이 대화 저장 단계에서 오류 나던 문제 |
| [84](https://github.com/rndigkwk/dograg/pull/84) | 2026-10-10 | 물결표(~) 범위가 화면에서 취소선으로 바뀌던 문제 |
| [85](https://github.com/rndigkwk/dograg/pull/85) | 2026-10-10 | fix: 처음 보는 말투의 진료비 질문 판별 개선 (holdout2 정답 17→20/20, 오분류 9→2/15) |
| [86](https://github.com/rndigkwk/dograg/pull/86) | 2026-10-10 | fix: 방문 보고서 재측정 — 답 없이 끝난 조사원 재질문 + 진료비 인용 지표 |
| [87](https://github.com/rndigkwk/dograg/pull/87) | 2026-10-10 | feat: 정기 평가에서 '답 없이 끝난 조사원' 횟수 감시 |
| [88](https://github.com/rndigkwk/dograg/pull/88) | 2026-10-10 | eval: 기본 관리 질문 30개 측정 (핵심 답함 20, 못 줌 7 — 주로 자료 구성 문제) |
| [89](https://github.com/rndigkwk/dograg/pull/89) | 2026-10-11 | feat: Cloud Run용 컨테이너 이미지 (로컬 2GB 제한에서 최고 1.06GiB) |
| [90](https://github.com/rndigkwk/dograg/pull/90) | 2026-10-11 | feat: GitHub Actions로 Cloud Run 배포 (키 파일 없는 인증) |
| [91](https://github.com/rndigkwk/dograg/pull/91) | 2026-10-11 | feat: 두 배포(Streamlit Cloud·Cloud Run) 함께 점검, README에 두 주소 |
| [92](https://github.com/rndigkwk/dograg/pull/92) | 2026-10-12 | docs: Docker·Cloud Run 배포 설계 문서와 README 반영 |
| [93](https://github.com/rndigkwk/dograg/pull/93) | 2026-10-12 | fix: 답 없이 끝난 조사원을 새 요청으로 다시 묻기 (재질문 성공 6/13 → 15/15) |
| [94](https://github.com/rndigkwk/dograg/pull/94) | 2026-10-12 | docs: 두 배포가 공유 DB 없이 도는 이유 (상태를 어디에 두나) |
| [95](https://github.com/rndigkwk/dograg/pull/95) | 2026-10-12 | fix: "3곳 알려줘"에 10곳이 나오던 문제 (개수 평가 11/18 → 18/18) |
| [96](https://github.com/rndigkwk/dograg/pull/96) | 2026-10-12 | fix: 앞선 질문이 새 주제의 검색을 망치던 문제 (holdout 주제 전환 0.38 → 1.0) |
