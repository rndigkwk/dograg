# 개선 기록: 측정 → 수정 → 검증

라그도그는 2026-09-28부터 10-18까지 PR 200여 개로 다듬었습니다(10-13 이후는 아래 9절). 이 문서는 그중 **문제를 숫자로 찾고, 고치고, 다시 재서 확인한** 사례를 모은 것입니다. 효과가 없어 **넣지 않은** 실험도 함께 남겼습니다. 기능별 설계와 이유는 [design.md](design.md)에, 실험의 자세한 기록은 [wiki/](wiki/)에 있습니다.

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
| [#112](https://github.com/rndigkwk/dograg/pull/112) | 질문 유형마다 다른 검색 전략 (Day 58 교안 3-3, 길이 × 질병·약 이름 4개 유형, 220문항) | useful@3 dense 0.827 · BM25 0.595 · 하이브리드 0.809, 유형별로 골라도 상한 0.836 (p=0.29). dense 대 하이브리드도 p=0.56 | 유형별 라우터 미적용, 하이브리드 유지 |
| [#62](https://github.com/rndigkwk/dograg/pull/62) | 보고서 답변의 병목이 생성이 아니라 검색 | 기준 답과 맞는 답 23 → **30/36** (p=0.016) | 보고서 검색도 BM25 + Dense 하이브리드 |
| [#77](https://github.com/rndigkwk/dograg/pull/77) [#78](https://github.com/rndigkwk/dograg/pull/78) | 상담 글은 길고 사용자 질문은 짧아 임베딩이 약함 | 짧은 질문 useful@3 0.600 → **0.783** (p=0.0001), 긴 질문 0.72 → **0.84** (p=0.023) | 보호자 말투 합성 질의($3.37)로 ko-sroberta 미세조정(Colab T4 4.6분), ONNX int8 |
| [#96](https://github.com/rndigkwk/dograg/pull/96) | 배포 앱에서 진료비·시설 질문 뒤의 건강 질문이 "자료에 없다" | holdout 주제 전환 0.38 → **1.0**, 시설 지역 4/6 → **6/6** (이어받기 0.72 → 0.64) | 앞선 질문을 모두 붙이지 않고, 모델이 혼자 읽히는 검색어를 씀 |
| [#105](https://github.com/rndigkwk/dograg/pull/105) | "며칠 전부터"가 든 건강 질문에 오늘 날짜로 답함 (CRAG 60 h08) | 날짜 판별 dev 5/11 → **11/11**, holdout 5/11 → **11/11**, 상담 질문 오판 886건(4.6%) → **0** | 기간 말이 있거나 20자 넘으면 날짜 질문 아님 |
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
| [#275](https://github.com/rndigkwk/dograg/pull/275) | NeMo Guardrails·Llama Guard 3·Prompt Guard 2를 앱 앞에 (레드팀 68문항) | 앱이 놓친 공격을 막은 층 없음(앱 26/26). NeMo 입력은 위기 질문 1·사람 약 2를 막음, Llama Guard 3는 정당한 질문 11개·질문당 66초 | 미적용 (함수 유지) |
| [#265](https://github.com/rndigkwk/dograg/pull/265) | GPU 리랭커(bge-reranker-v2-m3)를 운영 검색 후보에 | `기타` useful@3 0.79 → 0.78, 검증 100 0.84 → 0.86(p=0.63), CPU 질문당 **11.7초** | 미적용 |
| [#269](https://github.com/rndigkwk/dograg/pull/269) | 하드 네거티브로 임베딩 재학습(Day 74) | 짧은 질문 useful@3 0.80 → 0.742(p=0.09), 긴 상담 0.85 → 0.87(p=0.69) | 미적용, B 유지 |
| [#270](https://github.com/rndigkwk/dograg/pull/270) | 작은 분류기(앱 임베딩 + 로지스틱 회귀)로 Decisions 호출 대신 | 라우팅 22/24 vs Decisions 23/24, 응급 판단은 쓸 수 없음 | 미적용, Decisions 유지 |
| [#278](https://github.com/rndigkwk/dograg/pull/278) | Claude(Haiku 5.5·Opus 5.5)를 판사로 | 관련성 κ 0.28·0.30(지금 판사 0.64), 22쌍 사람과 일치 9/22·8/22 | 미적용 |
| [#276](https://github.com/rndigkwk/dograg/pull/276) | 프롬프트 캐시(고정 규칙을 앞에, 캐시 키) | 이 모델은 프롬프트 전체가 같을 때만 캐시 | 바꾸지 않음 |
| [#299](https://github.com/rndigkwk/dograg/pull/299) | 답변 판정 기준 2 판사를 병합 조건으로 | 사람 fail 17/20을 잡지만 사람 pass의 40%를 fail로 봄, κ 0.46 | 보조 지표로만 |
| [#295](https://github.com/rndigkwk/dograg/pull/295) | 레일 통합 때 NeMo self-check·Prompt Guard 2·Llama Guard 3 다시 검토 | 호출 +2번·약 +3초 / 메모리 4GiB 필요 / 8GiB·질문당 35~66초. 레드팀에서 새로 막은 공격 없음(#275) | 지금 검사를 레일로 묶기만(메모리·호출 그대로) |

## 8. 측정 방법 자체를 고친 경우

평가 지표가 틀리면 개선도 틀립니다. 지표를 의심해서 고친 경우입니다.

- **라벨 기반 정답 → "쓸모" 판정 (#50):** 정답 규칙이 기대는 라벨이 질문과 맞지 않아(#40에서 발견), 근거가 실제로 쓸모 있는지 LLM으로 판정하는 `useful@3`로 바꿨다. 판정 일치율도 함께 쟀다.
- **진료비 인용 지표의 빈틈 (#85, #86):** 처음 만든 "금액 일치" 지표가 해운대구 보고서의 대구 진료비 인용을 정답으로 셌다. 인용한 행과 금액이 서로 맞았기 때문이다. 그래서 "지역 일치" 지표를 더했다.
- **채점기 라벨 보정 (#85):** 구 값이 없을 때 앱이 시·도 값으로 답하는 경우를 채점기가 오답으로 셌다. 앱이 맞았다. 고치기 전 숫자도 보정한 채점기로 다시 쟀다.
- **실패 사유 오기 (#86):** API의 미완료 응답을 코드가 "호출 상한"으로 기록하고 있었다. 사유를 바로 적게 고쳐서 #93의 원인 조사가 가능해졌다.

## 9. 2026-10-13~18: 검색 이전, 화면·API 분리, 로그인, 보고서 근거

| PR | 발견 | 측정 (전 → 후) | 무엇을 바꿨나 |
| --- | --- | --- | --- |
| ADR-0007 | 앱 메모리가 무료 한도(약 1GB)에 붙어 있었다 | 앱 최고 메모리 910 → **442MB**, 검색 품질 같음 | 벡터·키워드 검색을 Supabase(pgvector halfvec + PGroonga)로, 장애 시 로컬 대체 |
| ADR-0008 (#160~#173) | 화면과 로직이 Streamlit 한 프로세스에 묶여 로그인·RLS를 붙이기 어려웠다 | 같은 품질 세트로 API 경로 확인 | Next.js(Vercel) + FastAPI(Cloud Run, SSE) 분리, Google 로그인 + RLS |
| 보안 점검 | User-Agent·`X-Forwarded-For` 위조로 질문 한도 우회 2건 | 배포 뒤 같은 공격 재시험: 막힘 | 비밀 헤더 토큰, 오른쪽 프록시 값, 위조 토큰 7종 거부 확인 ([보안](security/README.md)) |
| [#182](https://github.com/rndigkwk/dograg/pull/182), [#184](https://github.com/rndigkwk/dograg/pull/184) | 멈춘 방문 준비 실행이 서버 메모리에만 있어 인스턴스 1개 고정, 재배포 때 사라짐 | 다른 연결 풀에서 이어 가기 확인, 운영에서 멈춤→답→보고서 확인 | Supabase `visit_prep` Postgres 체크포인터(30분), 인스턴스 최대 2 |
| [#190](https://github.com/rndigkwk/dograg/pull/190) | 큰 한국어 임베딩(KURE-v1)을 미세조정하면 나을까 | 하이브리드 0.805 vs 앱 0.809(p=1.0), 질문 임베딩 8배 느림 | **바꾸지 않음**. 학습과 비교를 MLflow(DagsHub)에 기록 |
| [#192](https://github.com/rndigkwk/dograg/pull/192) | 보고서 근거에 목차·참고문헌이 섞이고, 답이 목차의 쪽수를 인용 | 섞인 페이지 5 → 0(18문항), 정답 페이지 16/18 그대로 | 목차·참고문헌 조각 70개 제외, 근거 머리표의 쪽수만 인용 |
| [#198](https://github.com/rndigkwk/dograg/pull/198) | KB 보고서는 숫자를 전용 글꼴로 넣어 PDF 텍스트에서 숫자가 빠졌다(112쪽 중 91쪽) | "펫보험 가입률" 오답 → 정답, 전체 15/18 유지 | OCR 조각 147개 추가(data-v5), 근거에 "스캔 글(OCR)" 표시(#199) |
| [#201](https://github.com/rndigkwk/dograg/pull/201) | 같은 쪽의 PDF·OCR 조각이 상위 근거 6자리 중 7자리(18문항 합)를 겹쳐 차지 | 정답 15 → 16/18, 오답 0 | 근거를 조각 6개가 아니라 쪽 6개로 셈 |
| [#202](https://github.com/rndigkwk/dograg/pull/202), [#203](https://github.com/rndigkwk/dograg/pull/203) | 두 보고서를 함께 물으면 한 보고서가 근거를 독차지. 로컬에서 고친 것이 **운영 검색(PGroonga)에서는 틀림** | r03: 부분 정답 3회 → 정답 3/3(운영 검색 기준) | 보고서마다 주제어로 그 보고서 안에서만 찾기. 검색 변경은 운영 검색으로도 잼 |
| [#194](https://github.com/rndigkwk/dograg/pull/194), [#195](https://github.com/rndigkwk/dograg/pull/195) | 지난 상담을 기억하되 보호자가 통제해야 한다(ADR-0009) | 관련 노트 반영 6/6, 무관 노트 끌어옴 0/4. 판사가 놓친 날짜 오판 3/6 → 6/6 | 버튼으로 만드는 상담 노트(RLS, 기본 꺼짐), 경과일을 프롬프트에 적어 넣음 |

- **이 기간의 교훈 두 가지:** (1) 판사 점수가 만점이어도 답을 직접 읽어야 한다(노트 날짜 오판). (2) 검색 수정은 로컬과 운영 검색 엔진이 달라 운영 검색으로도 재야 한다(#202 → #203).

## 10. 2026-10-18~20: 운영 안정화, 병합 게이트, 공공 돌봄 지침

| PR | 발견 | 측정 (전 → 후) | 무엇을 바꿨나 |
| --- | --- | --- | --- |
| [#211](https://github.com/rndigkwk/dograg/pull/211), [#218](https://github.com/rndigkwk/dograg/pull/218) | 운영 키워드 검색(PGroonga)이 로컬(Kiwi BM25)과 순위가 달랐다 | 건강: precision@3 0.73 → **0.94**(키워드 쪽 제거, p=5e-9), 보고서 h04 정답 | 보고서 키워드는 메모리 안 BM25, 건강은 의미 검색만 |
| [#216](https://github.com/rndigkwk/dograg/pull/216), [#222](https://github.com/rndigkwk/dograg/pull/222) | 자료와 먼 질문, 다른 동물 질문에도 근거 평가·재검색을 돌렸다 | 검증 561문항의 최저 유사도 0.407, 범위 밖 20문항 중 3개가 0.4 아래 → 모델 호출 없이 보류 | 유사도 하한 0.4, 다른 동물은 검색 전에 보류 |
| [#212](https://github.com/rndigkwk/dograg/pull/212), [#213](https://github.com/rndigkwk/dograg/pull/213), [#217](https://github.com/rndigkwk/dograg/pull/217), [#220](https://github.com/rndigkwk/dograg/pull/220) | 배포 뒤 확인과 품질 판정이 사람 손에 달려 있었다 | 실패한 안정 문항을 두 번 더 물어 흔들림(u20)과 회귀를 구분 | 릴리스 점검 6항목·롤백 워크플로, SLO 주간 보고·실패 이슈, 병합 조건 네 가지 |
| [#219](https://github.com/rndigkwk/dograg/pull/219) | LLM 판사를 믿어도 되나, 리랭킹 API는 나을까 | 관련도 판사 κ 0.636(사람 라벨), Cohere useful@3 0.80 vs 지금 0.84 | 판사 성적표를 기록, 리랭킹은 넣지 않음 |
| [#225](https://github.com/rndigkwk/dograg/pull/225), [#226](https://github.com/rndigkwk/dograg/pull/226), [#227](https://github.com/rndigkwk/dograg/pull/227) | 방문 준비 보고서를 병원에 가져가기 어렵고, 지난 상담을 못 쓰고, 멈추면 처음부터 | 실제 그래프 테스트: 이어 가기는 끝낸 단계를 다시 하지 않음 | 인쇄·PDF, 고른 상담 노트 넣기, 마지막 체크포인트부터 이어 만들기(2번까지) |
| [#228](https://github.com/rndigkwk/dograg/pull/228), [#233](https://github.com/rndigkwk/dograg/pull/233), [#236](https://github.com/rndigkwk/dograg/pull/236) | 일상 관리 질문의 1/4을 못 답했다. 원인은 자료 구성(증상 상담 위주) | 기본 관리 30문항 핵심 답함 20 → **26**, 지침 질문 16개 중 13 → **15** | 공공 지침 5종(이용 조건 확인, 이미지 PDF는 모델로 옮겨 적고 원본과 대조), 문맥을 문장 단위로 |
| [#229](https://github.com/rndigkwk/dograg/pull/229), [#235](https://github.com/rndigkwk/dograg/pull/235) | 사체 처리·펫로스·사망 신고 질문이 시설 검색·서비스 안내로 갔다 | 이별 질문 → 건강 상담: dev 2/12 → 12/12, 새 holdout 4/10 → 8/10 | 이별 낱말 규칙, 통계·시설 질문은 그대로 |
| [#230](https://github.com/rndigkwk/dograg/pull/230), [#231](https://github.com/rndigkwk/dograg/pull/231), [#232](https://github.com/rndigkwk/dograg/pull/232) | 지침을 보고서와 일정에도 쓰고, 운영에서 쓰임을 재야 했다 | 노견 상담 보고서가 리플릿 2쪽을 근거로 인용 | 방문 준비 조사원의 지침 검색, 관리 일정 페이지, 실행 기록의 `guide_count` |
| [#238](https://github.com/rndigkwk/dograg/pull/238), [#239](https://github.com/rndigkwk/dograg/pull/239), [#240](https://github.com/rndigkwk/dograg/pull/240) | 평가에 쓴 비용으로 OpenAI 한도가 차서 **운영 챗봇이 멈춤**. 데이터만 바꾼 PR은 게이트를 건너뜀 | 장애 중 운영에서 안내 + 지침·상담 표시 확인 | 한도 오류면 모델 없이 검색 결과만, 키 분리 절차, 데이터 버전도 게이트 대상 |

- **이 기간의 교훈 두 가지:** (1) 평가와 운영이 같은 키를 쓰면 평가 비용이 운영 장애가 된다. 키를 나누고, 외부 모델이 멈춰도 쓸모 있는 화면을 남긴다. (2) 이미 본 holdout으로는 고친 효과를 잴 수 없다. 고치기 전에 새 holdout을 쓴다(#235).

## 11. 2026-10-21~23: 가드레일 통합 운영, 다른 계열 모델로 교차 검증

| PR | 발견 | 측정 (전 → 후) | 무엇을 바꿨나 |
| --- | --- | --- | --- |
| [#266](https://github.com/rndigkwk/dograg/pull/266), [#267](https://github.com/rndigkwk/dograg/pull/267) | 위기 표현에 상담 번호가 없었고, 검색 자료·메모 속 지시와 지어낸 링크를 막는 장치가 없었다 | 위기 0/4 → **4/4**, 숨은 지시·위기 패턴 오탐 0(상담 19,206개) | 위기 안내를 맨 앞에, 검색 레일, 허용 밖 링크 제거 |
| [#268](https://github.com/rndigkwk/dograg/pull/268), [#273](https://github.com/rndigkwk/dograg/pull/273) | 답의 어느 문장이 어느 사례에서 왔는지 볼 수 없었다 | 문장 인용률 0 → 0.44, 지어낸 숫자 0/19 유지 | `[사례 n]` 인용과 숫자 출처 검사(모델 없음), 웹·Streamlit 근거 번호 맞춤 |
| [#274](https://github.com/rndigkwk/dograg/pull/274), [#282](https://github.com/rndigkwk/dograg/pull/282), [#283](https://github.com/rndigkwk/dograg/pull/283) | 레드팀을 손으로 돌릴 때만 쟀다 | 기준선 67/68, 이후 5회 실행으로 안정 문항 65 | 주간 회귀·가드레일 PR 게이트에 레드팀, 레일 알림 2개, 공격·위기는 회귀로·정상 질문은 통과율로 판정 |
| [#276](https://github.com/rndigkwk/dograg/pull/276) | 건강 답변 시간 대부분이 답변 모델의 추론이었다 | p90 18.5 → **11.4초**, 사람 블라인드 22쌍 low 6 · medium 5 · 비슷함 11 | 답변 생성 추론 low (판사 대신 사람이 결정) |
| [#277](https://github.com/rndigkwk/dograg/pull/277), [#279](https://github.com/rndigkwk/dograg/pull/279), [#280](https://github.com/rndigkwk/dograg/pull/280) | 다른 모델(Claude)이 쓴 위기 문항 3개 중 2개를 놓쳤고, 패턴을 고친 뒤 새 문항에서 다시 0/5 | 모델 판정 추가 뒤 12/12, 오탐 0/305, 판정 뒤 새 holdout **5/5**, 운영 5/5 | 정규식은 첫 단계로 두고, 답변과 동시에 모델이 위기 여부 판정 |
| [#278](https://github.com/rndigkwk/dograg/pull/278) | 판사가 모두 OpenAI 계열이라 자기 선호를 의심했다 | 관련성 κ: 지금 판사 0.64, Claude Haiku 0.28 · Opus 0.30. 답변 fail 3개는 판사 다섯 모두 0/3 | 판사는 그대로, 원인은 기준 문장(#279에서 기준 2와 라벨 30칸) |
| [#281](https://github.com/rndigkwk/dograg/pull/281) | 긴 상담 속 비용 질문에 비용 이야기가 없었다(사용자 메모) | 검증 상담 6.8%에 안내가 붙음 | 건강 답 끝에 진료비 안내 한 줄(모델 없음) |

- **이 기간의 교훈 두 가지:** (1) 같은 사람이 방어와 시험을 함께 쓰면 빈틈을 못 본다. 다른 계열 모델이 쓴 문항이 위기 안내의 빈틈을 두 번 찾았다. 표현을 하나씩 더하는 정규식으로는 따라갈 수 없어 모델 판정을 붙였다. (2) 판사 계열이나 크기를 바꿔도 사람 판정과 맞지 않았다. 답변 품질이 걸린 결정(답변 추론 low)은 블라인드 사람 판정으로 했다.

## 12. 2026-10-23~24: 운영 신뢰성, 레일 통합, 사용자 피드백으로 답 다듬기, 웹 리디자인

| PR | 발견 | 측정 (전 → 후) | 무엇을 바꿨나 |
| --- | --- | --- | --- |
| [#289](https://github.com/rndigkwk/dograg/pull/289) | API에는 Streamlit과 달리 검색 미리 읽기가 없어, 새 인스턴스의 첫 건강 질문이 모델·DB 연결을 읽었다 | 첫 질문이 내던 읽기 4~7초(로컬, 이미지와 같은 의존성), 배포 검사 첫 건강 질문 9.6~10.8초(그동안 중앙값 13.8초) | 시작 단계(lifespan)에서 미리 읽기. Cloud Run은 요청 사이 CPU가 거의 없어 백그라운드 스레드가 아니다 |
| [#292](https://github.com/rndigkwk/dograg/pull/292) | 모델 호출에 제한 시간이 없어 기본값(요청당 600초, 재시도 2번)이었다 | 실제 0.001초 제한 → `APITimeoutError` → 검색 결과로 넘어감 | 평가·위기 20초, 일반 30초, 답 45초, 재시도 1번. 시간 초과·연결 실패도 한도 초과처럼 검색 근거와 안내 |
| [#293](https://github.com/rndigkwk/dograg/pull/293) | 최소 권한을 점검한 적이 없었다(Day 64 실행 레일) | DB `ragdog_app`·에이전트 도구·토큰은 맞음. 빈틈 2개: CI가 API와 같은 DB 계정, 배포 계정이 프로젝트 전체 `run.admin`·모든 브랜치 | 점검표와 고치는 명령(`docs/security/least-privilege.md`, 실행은 소유자) |
| [#295](https://github.com/rndigkwk/dograg/pull/295) | 검사가 여러 파일에 흩어져 있어, 무엇이 켜져 있는지 한곳에서 볼 수 없었다 | 동작·호출·메모리 그대로(레드팀 게이트 통과) | `rails/rails.yml`: 단계별 규칙 id(IN/RET/ANS/OUT/EXE), 줄을 빼면 꺼짐, 위기·개인정보·실행 제한은 못 뺌, 로그에 `rules` |
| [#296](https://github.com/rndigkwk/dograg/pull/296) | 답이 견종·나이 차이에 매달렸다(사용자) | 견종·나이 차이를 짚은 답 3/20 → **0/20**(h01~h20) | 견종은 따지지 않고, 나이는 2살 이하나 같은 시기면 언급하지 않음 |
| [#297](https://github.com/rndigkwk/dograg/pull/297) | 입력 레일(개인정보 가림)이 검사 수치를 주소로 읽어 모델에 가기 전에 지웠다("백혈구 수치가 22,000" → "[주소],000") | 상담 자료 스캔에서 바뀐 곳 16 → **0**, 실제 주소 4개는 그대로 가림 | "가"는 숫자 뒤만 길 이름, 범위·목록·천 단위 숫자는 번지가 아님 |
| [#298](https://github.com/rndigkwk/dograg/pull/298) | 답이 병원에 가 보라고만 했다(사용자) | 병원·수의사 문장 48% → **31%**, 병원으로 시작하는 답은 급한 4개만(소변 못 봄, 부기·무기력, 출혈 지속, 초콜릿) | 병원 권고는 끝에 한 번, 언제 가야 하는지와 함께. 원인·관찰·관리 요령 먼저 |
| [#290](https://github.com/rndigkwk/dograg/pull/290), [#299](https://github.com/rndigkwk/dograg/pull/299) | 판사 다섯이 사람의 fail을 놓친 원인이 기준 문장인지 확인 | 사람 라벨 60칸: 같은 판사가 기준 1로 fail 5/20, 기준 2로 **17/20**(κ 0.11 → 0.46) | 기준 2는 보조 지표로만(사람 pass의 40%를 fail로 봄) |
| [#291](https://github.com/rndigkwk/dograg/pull/291), [#300](https://github.com/rndigkwk/dograg/pull/300) | 웹 첫 화면에 마크다운 라이브러리, 큰 사진, 낮은 대비, 채팅 흔들림 | 채팅 첫 JS 232 → 188kB, 홈 사진 357 → 138KB, 채팅 접근성 95 → **100**, CLS 0.123 → **0** | 마크다운 따로 받기, 4:3 크기 사진, 보조 글자색, 저장 안내 위치 |
| [#301](https://github.com/rndigkwk/dograg/pull/301) | 대기 중에 이유·시간을 알 수 없었고, 실패하면 같은 질문을 다시 쳐야 했다 | 화면 테스트 4개(503 뒤 다시 보내기, 멈추기) | 경과 초, 서버 깨우는 중 안내, 멈추기, 원인별 오류 문구와 다시 시도 |
| [#302](https://github.com/rndigkwk/dograg/pull/302), [#303](https://github.com/rndigkwk/dograg/pull/303), [#304](https://github.com/rndigkwk/dograg/pull/304), [#305](https://github.com/rndigkwk/dograg/pull/305) | 최상위 메뉴 10개가 넘쳐 잘렸고, 홈은 질문까지 두 번 눌러야 했고, 진료비 막대가 다 같은 길이였다 | 메뉴 10 → 4묶음, 휴대폰 하단 탭, 모든 글자 4.5:1 이상, 시·도 중간값(8,000~10,000원)이 점 위치로 구분됨 | 리디자인 A안(시안 두 가지 중 선택): 메뉴, 홈 질문창, 선 아이콘, 진료비 점 그래프 |

- **이 기간의 교훈:** 사용자가 직접 써 보고 남긴 두 마디("견종·나이에 집착한다", "병원에만 가라고 한다")가 평가 지표로는 안 보이던 문제였다. 둘 다 원인은 오래전에 넣은 안전 규칙(넓혀 적용하지 말 것, 진료 권고는 써도 됨)이 너무 넓게 적용된 것이었다. 규칙을 좁히고 같은 20문항으로 전후를 재서 확인했다.

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
| [97](https://github.com/rndigkwk/dograg/pull/97) | 2026-10-12 | docs: 개선 기록(측정 → 수정 → 검증)과 기능별 설계 문서 |
| [98](https://github.com/rndigkwk/dograg/pull/98) | 2026-10-12 | fix: 시설 단어 없는 시설 후속 질문을 건강 검색 맥락에서 제외 |
| [99](https://github.com/rndigkwk/dograg/pull/99) | 2026-10-12 | fix: 건강 답변이 아는 내용부터 쓰고, 없는 부분은 뒤에 밝힘 |
| [100](https://github.com/rndigkwk/dograg/pull/100) | 2026-10-12 | perf: Langfuse 이벤트 줄이기 (로컬 평가 추적 끔, LangChain 군더더기 span 제외) |
| [101](https://github.com/rndigkwk/dograg/pull/101) | 2026-10-12 | fix: 다른 보호자의 상담 사례를 지금 보호자의 병력처럼 쓰지 않기 |
| [102](https://github.com/rndigkwk/dograg/pull/102) | 2026-10-12 | fix: 답변 중에는 입력창 닫기 (새 질문이 진행 중인 답을 끊던 문제) |
| [103](https://github.com/rndigkwk/dograg/pull/103) | 2026-10-12 | eval: 가드레일 현재 상태 측정 (수업 전 기준선, 수정 없음) |
| [104](https://github.com/rndigkwk/dograg/pull/104) | 2026-10-12 | docs: 앞으로 배울 내용(Day 58~79) 중 이 프로젝트에 쓸 만한 것 |
| [105](https://github.com/rndigkwk/dograg/pull/105) | 2026-10-12 | fix: "며칠 전부터"가 든 건강 질문에 오늘 날짜로 답하던 문제 |
| [106](https://github.com/rndigkwk/dograg/pull/106) | 2026-10-12 | fix: 일반 대화를 모델 대신 고정 문구로 (ChatGPT 사칭·범위 밖 수행 제거) |
| [107](https://github.com/rndigkwk/dograg/pull/107) | 2026-10-13 | docs: curriculum-fit에 #105·#106 적용 결과 반영 |
| [108](https://github.com/rndigkwk/dograg/pull/108) | 2026-10-13 | docs: 아키텍처 결정 기록(ADR) 소급 작성 |
| [109](https://github.com/rndigkwk/dograg/pull/109) | 2026-10-13 | eval: 벡터 저장소 비교 (Day 58 교안 방식) + ADR-0003 제안 |
| [110](https://github.com/rndigkwk/dograg/pull/110) | 2026-10-13 | docs: 임베딩 결정을 네 축 점수로 다시 정리 (Day 58 방식, 새 측정 없음) |
| [111](https://github.com/rndigkwk/dograg/pull/111) | 2026-10-13 | feat: 메모리 안 전수 검색 저장소 + ADR-0003 확정 (앱 최고 메모리 991 → 910MB) |
| [112](https://github.com/rndigkwk/dograg/pull/112) | 2026-10-13 | eval: 질문 유형별 검색 전략 측정 (Day 58 3-3) — 라우터 불필요 |
| [113](https://github.com/rndigkwk/dograg/pull/113) | 2026-10-13 | eval: pgvector 서울 리전 재측정, ADR-0004 거절, ADR-0003 유지 |
| [114](https://github.com/rndigkwk/dograg/pull/114) | 2026-10-13 | eval: Supabase(pgvector + PGroonga) 검색 측정 — 앱 메모리 910 → 442MB (ADR-0007 제안), 지역은 서울 유지 (ADR-0006) |
| [115](https://github.com/rndigkwk/dograg/pull/115) | 2026-10-13 | eval: 기본 임베딩 비교 — multilingual-e5-small vs ko-sroberta |
| [116](https://github.com/rndigkwk/dograg/pull/116) | 2026-10-13 | eval: 건강 상담 글 128토큰 잘림 — 길이 늘리기·청킹 비교 (지금 유지) |
| [117](https://github.com/rndigkwk/dograg/pull/117) | 2026-10-13 | feat: Supabase 검색 준비 — 장애 시 로컬 검색으로 넘어가기, float16 저장 (ADR-0007) |
| [118](https://github.com/rndigkwk/dograg/pull/118) | 2026-10-13 | deploy: Cloud Run에 Supabase 검색 연결 + 질문별 메모리 기록 (#117 병합 뒤 커밋) |
| [119](https://github.com/rndigkwk/dograg/pull/119) | 2026-10-13 | docs: ADR-0007 채택 — 두 배포 Supabase 검색 확인, ADR-0003 대체됨 |
| [120](https://github.com/rndigkwk/dograg/pull/120) | 2026-10-13 | feat: Supabase 장애 대비 검색을 가볍게 — Chroma·Kiwi 없이 (장애 중 최고 1,226 → 738MB) |
| [121](https://github.com/rndigkwk/dograg/pull/121) | 2026-10-13 | eval: KURE-v1 건강 검색 비교 — 지금 모델 유지 (하이브리드 0.809 대 0.723) |
| [122](https://github.com/rndigkwk/dograg/pull/122) | 2026-10-13 | docs: 128토큰 잘림이 덜 아픈 이유를 측정대로 고침 + 건강 검색이 임베딩하는 범위 |
| [123](https://github.com/rndigkwk/dograg/pull/123) | 2026-10-13 | ops: 배포 점검에 건강 질문 추가 + Supabase 검색 확인 (무료 프로젝트 일시 정지 방지) |
| [124](https://github.com/rndigkwk/dograg/pull/124) | 2026-10-13 | fix: 개인정보를 모델에 보내기 전에 가리기 (OpenAI로 나감 8/8 → 0/8) |
| [125](https://github.com/rndigkwk/dograg/pull/125) | 2026-10-13 | fix: 건강 답변이 질문에 끼워 넣은 지시를 따르지 않게 (주입 dev 3/4 → 4/4) |
| [126](https://github.com/rndigkwk/dograg/pull/126) | 2026-10-13 | fix: 감사 인사 단어 보강 (새 holdout 감사 1/6 → 6/6) |
| [127](https://github.com/rndigkwk/dograg/pull/127) | 2026-10-13 | ops: 배포가 옛 커밋으로 남으면 점검이 실패하게 (Streamlit 재부팅 필요 감지) |
| [128](https://github.com/rndigkwk/dograg/pull/128) | 2026-10-13 | docs: Langfuse 사용량 다시 측정 — 다음 주기 월 1만 5천 안팎 예상 |
| [129](https://github.com/rndigkwk/dograg/pull/129) | 2026-10-14 | ops: 주간 회귀 기준을 품질 지표와 운영 경보로 나누기 (세트마다 품질 5개 이하) |
| [130](https://github.com/rndigkwk/dograg/pull/130) | 2026-10-14 | eval: 건강 답변 정확도(수의사 답 대조)를 측정하고 주간 회귀 품질 지표로 추가 |
| [131](https://github.com/rndigkwk/dograg/pull/131) | 2026-10-14 | fix: 긴 건강 상담글이 키워드 하나로 시설 검색·일반 대화·보고서로 가던 문제 (holdout 28/461 → 1/461) |
| [132](https://github.com/rndigkwk/dograg/pull/132) | 2026-10-14 | ci: 답변 경로를 바꾸는 PR에만 품질 검사 (CRAG 60 + 라우팅 36) |
| [133](https://github.com/rndigkwk/dograg/pull/133) | 2026-10-14 | fix: Supabase 표를 공개 REST API에서 닫기 (RLS 켜기, 공개 역할 권한 회수) |
| [134](https://github.com/rndigkwk/dograg/pull/134) | 2026-10-15 | feat: 👎에 이유 고르기 + 동의하면 질문·답변을 개인정보 가려 저장 (운영 중 평가 입력) |
| [135](https://github.com/rndigkwk/dograg/pull/135) | 2026-10-15 | feat: 자료에 없던 주제 모으기 (답변 속 '자료에 없다' 문장, 배포 앱만, 개인정보 가림) |
| [136](https://github.com/rndigkwk/dograg/pull/136) | 2026-10-15 | fix: 배포 확인용 질문은 자료 빈칸 표에서 빼기 |
| [137](https://github.com/rndigkwk/dograg/pull/137) | 2026-10-15 | eval: 판사 모델 이름을 결과에 남기고, 판사가 바뀌면 주간 기준을 실패로 |
| [138](https://github.com/rndigkwk/dograg/pull/138) | 2026-10-15 | eval: LLM 판사 검증 (다시 묻기·순서·다른 판사·편향, 사람 판정 성적표) |
| [139](https://github.com/rndigkwk/dograg/pull/139) | 2026-10-15 | eval: 평가 범위표 (치과 0문항, 보고서 보류 2, 범위 밖 라우팅 1) |
| [140](https://github.com/rndigkwk/dograg/pull/140) | 2026-10-15 | ops: 주간 회귀·배포 확인 결과를 Supabase에 쌓아 추세 보기 |
| [141](https://github.com/rndigkwk/dograg/pull/141) | 2026-10-15 | feat: 자동 기억 (건강 질문 속 새 진단·약·수술·체중을 기억할지 제안) |
| [142](https://github.com/rndigkwk/dograg/pull/142) | 2026-10-15 | fix: 간식·사료·산책 같은 일상 돌봄 질문을 건강 답변으로 보내기 |
| [143](https://github.com/rndigkwk/dograg/pull/143) | 2026-10-15 | fix: 자동 기억이 '두부'처럼 음식 이름인 반려견도 알아보게 |
| [144](https://github.com/rndigkwk/dograg/pull/144) | 2026-10-15 | fix: 저장된 프로필을 읽기 전에는 기억 제안을 띄우지 않기 |
| [145](https://github.com/rndigkwk/dograg/pull/145) | 2026-10-15 | feat: 질문 횟수 제한 (한 사람 시간당 10번, 하루 30번) |
| [146](https://github.com/rndigkwk/dograg/pull/146) | 2026-10-15 | ops: 평가 스크립트가 예상 모델 호출 수를 보여 주고 200번을 넘으면 멈추기 |
| [147](https://github.com/rndigkwk/dograg/pull/147) | 2026-10-15 | fix: 보호자 이름과 구/군 없는 주소도 가리기 |
| [148](https://github.com/rndigkwk/dograg/pull/148) | 2026-10-15 | ops: 👎 대화를 보고 평가 세트 후보로 내보내는 스크립트 |
| [149](https://github.com/rndigkwk/dograg/pull/149) | 2026-10-15 | ops: main은 Cloud Run에만 배포, Streamlit Cloud는 고정된 백업만 |
| [150](https://github.com/rndigkwk/dograg/pull/150) | 2026-10-15 | chore: 실수로 들어간 dev container 폴더 지우기 |
| [151](https://github.com/rndigkwk/dograg/pull/151) | 2026-10-15 | ops: 앱 표는 없을 때만 만들고 잠그기 (앱 전용 DB 계정 준비) |
| [152](https://github.com/rndigkwk/dograg/pull/152) | 2026-10-15 | docs: ADR-0008 (채택) Next.js 화면 + FastAPI 백엔드 + Supabase Auth/RLS |
| [153](https://github.com/rndigkwk/dograg/pull/153) | 2026-10-15 | feat: API 뼈대 (ADR-0008 P1) — /health와 CORS |
| [154](https://github.com/rndigkwk/dograg/pull/154) | 2026-10-15 | feat: POST /chat 답변 스트리밍 (ADR-0008 P1) |
| [155](https://github.com/rndigkwk/dograg/pull/155) | 2026-10-15 | feat: GET /places 시설 검색 API (ADR-0008 P1) |
| [156](https://github.com/rndigkwk/dograg/pull/156) | 2026-10-15 | feat: GET /stats/overview 데이터 소개 수치 API (ADR-0008 P1) |
| [157](https://github.com/rndigkwk/dograg/pull/157) | 2026-10-15 | feat: POST /visit-prep 방문 준비 보고서 스트리밍 (ADR-0008 P1) |
| [158](https://github.com/rndigkwk/dograg/pull/158) | 2026-10-15 | feat: /chat 기억 제안 이벤트와 POST /feedback (ADR-0008 P1) |
| [159](https://github.com/rndigkwk/dograg/pull/159) | 2026-10-15 | ops: API를 별도 Cloud Run 서비스 ragdog-api로 배포 (ADR-0008 P1) |
| [160](https://github.com/rndigkwk/dograg/pull/160) | 2026-10-15 | eval: 배포된 API로 CRAG·라우팅 품질 확인 (ADR-0008 P1) |
| [161](https://github.com/rndigkwk/dograg/pull/161) | 2026-10-15 | feat(web): Next.js 채팅 화면과 답변 스트리밍 (ADR-0008 P2-1) |
| [162](https://github.com/rndigkwk/dograg/pull/162) | 2026-10-15 | feat(web): 답변 아래 근거와 피드백 (ADR-0008 P2-2) |
| [163](https://github.com/rndigkwk/dograg/pull/163) | 2026-10-16 | feat(web): 대화 기록을 브라우저에 저장 (ADR-0008 P2-3a) |
| [164](https://github.com/rndigkwk/dograg/pull/164) | 2026-10-16 | feat(web): 반려견 프로필, 기억 제안, 현재 위치 (ADR-0008 P2-3b) |
| [165](https://github.com/rndigkwk/dograg/pull/165) | 2026-10-16 | test(web): Playwright 화면 흐름 + Vercel 연결 (ADR-0008 P2-4) |
| [166](https://github.com/rndigkwk/dograg/pull/166) | 2026-10-16 | feat(web): 상단 메뉴와 시설 찾기 화면 (ADR-0008 P3-1) |
| [167](https://github.com/rndigkwk/dograg/pull/167) | 2026-10-16 | feat(web): 데이터 소개 화면과 막대 차트 (ADR-0008 P3-2) |
| [168](https://github.com/rndigkwk/dograg/pull/168) | 2026-10-16 | feat(web): 방문 준비 보고서 화면 (ADR-0008 P3-3) |
| [169](https://github.com/rndigkwk/dograg/pull/169) | 2026-10-16 | feat(web): 홈 화면, Streamlit 다섯 화면 이전 완료 (ADR-0008 P3-4) |
| [170](https://github.com/rndigkwk/dograg/pull/170) | 2026-10-16 | security: 로그인 전 보안 점검과 질문 한도 우회 차단 |
| [171](https://github.com/rndigkwk/dograg/pull/171) | 2026-10-16 | feat(db): 로그인 사용자 기록 표와 RLS (ADR-0008 P4-1) |
| [172](https://github.com/rndigkwk/dograg/pull/172) | 2026-10-16 | feat(web): Supabase Auth Google 로그인 (ADR-0008 P4-2) |
| [173](https://github.com/rndigkwk/dograg/pull/173) | 2026-10-16 | fix(web): 좁은 화면에서 로그인 버튼이 안 보이던 문제 |
| [174](https://github.com/rndigkwk/dograg/pull/174) | 2026-10-16 | feat(web): 시설 지도 마우스 휠 확대·축소 |
| [175](https://github.com/rndigkwk/dograg/pull/175) | 2026-10-16 | feat(web): 로그인하면 기록을 계정에 저장 (ADR-0008 P4-3) |
| [176](https://github.com/rndigkwk/dograg/pull/176) | 2026-10-16 | feat: 로그인 사용자는 계정 기준으로 질문 한도 (ADR-0008 P4-4) |
| [177](https://github.com/rndigkwk/dograg/pull/177) | 2026-10-16 | docs(security): 로그인 뒤 보안 점검 결과 |
| [178](https://github.com/rndigkwk/dograg/pull/178) | 2026-10-16 | feat: 관리자 키 없이 계정 삭제 (DB 함수) |
| [179](https://github.com/rndigkwk/dograg/pull/179) | 2026-10-16 | feat: 방문 준비 보고서 현재 위치 기반 병원 + Word·텍스트 저장 |
| [180](https://github.com/rndigkwk/dograg/pull/180) | 2026-10-16 | docs(security): 로그인 점검 후속 결과 |
| [181](https://github.com/rndigkwk/dograg/pull/181) | 2026-10-16 | docs: 교안 재검토 (메모리·서버 저장 제약 해제 후, Day 57~61 추가) |
| [182](https://github.com/rndigkwk/dograg/pull/182) | 2026-10-16 | feat(api): 방문 준비 보고서의 멈춘 실행을 Supabase에 저장 |
| [183](https://github.com/rndigkwk/dograg/pull/183) | 2026-10-16 | fix(api): visit_prep 스키마가 없으면 메모리 저장소로 돌아가기 |
| [184](https://github.com/rndigkwk/dograg/pull/184) | 2026-10-16 | ops(api): API 인스턴스를 최대 2개로 |
| [185](https://github.com/rndigkwk/dograg/pull/185) | 2026-10-16 | feat(ml): KURE-v1 미세조정 노트북과 MLflow(DagsHub) 기록 |
| [186](https://github.com/rndigkwk/dograg/pull/186) | 2026-10-16 | feat(ml): 이전 임베딩 비교를 MLflow 기준선으로 |
| [187](https://github.com/rndigkwk/dograg/pull/187) | 2026-10-16 | feat(web): 지역별 진료비 탭 (시도 그래프, 시군구 표) |
| [188](https://github.com/rndigkwk/dograg/pull/188) | 2026-10-16 | fix(ml): KURE-v1 미세조정을 T4 메모리에 맞추기 |
| [189](https://github.com/rndigkwk/dograg/pull/189) | 2026-10-16 | feat(web): PDF 보고서 분석 탭 |
| [190](https://github.com/rndigkwk/dograg/pull/190) | 2026-10-16 | docs(ml): KURE-v1 미세조정 결과 — 앱 모델 유지 |
| [191](https://github.com/rndigkwk/dograg/pull/191) | 2026-10-17 | ci(eval): 주간 회귀 평가를 MLflow(DagsHub)에도 기록 |
| [192](https://github.com/rndigkwk/dograg/pull/192) | 2026-10-17 | fix(report): 보고서 근거에서 목차·참고문헌 페이지 빼기 |
| [193](https://github.com/rndigkwk/dograg/pull/193) | 2026-10-17 | docs(adr): ADR-0009 지난 상담 기억 (상담 노트) 채택 |
| [194](https://github.com/rndigkwk/dograg/pull/194) | 2026-10-17 | feat: 지난 상담 기억 — 상담 노트 (ADR-0009) |
| [195](https://github.com/rndigkwk/dograg/pull/195) | 2026-10-17 | fix(notes): 지난 상담 기록에 경과일을 적어 날짜 오판 막기 |
| [196](https://github.com/rndigkwk/dograg/pull/196) | 2026-10-17 | docs(security): 보안 정리 문서 (현재 상태 + 10-17 점검) |
| [197](https://github.com/rndigkwk/dograg/pull/197) | 2026-10-17 | feat: 피드백·데이터 공백 기록 3년 뒤 자동 삭제 |
| [198](https://github.com/rndigkwk/dograg/pull/198) | 2026-10-17 | feat(report): KB 보고서의 사라진 숫자를 OCR로 보완 (data-v5) |
| [199](https://github.com/rndigkwk/dograg/pull/199) | 2026-10-17 | feat(report): OCR로 읽은 근거에 '스캔 글(OCR)' 표시 |
| [200](https://github.com/rndigkwk/dograg/pull/200) | 2026-10-17 | feat(notes): 노트 30개가 차면 모델 호출 없이 기억 화면으로 안내 |
| [201](https://github.com/rndigkwk/dograg/pull/201) | 2026-10-17 | fix(report): 같은 쪽의 PDF·OCR 조각은 근거 한 자리로 |
| [202](https://github.com/rndigkwk/dograg/pull/202) | 2026-10-17 | fix(report): 두 보고서를 묻는 질문은 보고서마다 근거 찾기 |
| [203](https://github.com/rndigkwk/dograg/pull/203) | 2026-10-17 | fix(report): 두 보고서 질문은 보고서마다 주제어로 찾기 (운영 검색 기준) |
| [204](https://github.com/rndigkwk/dograg/pull/204) | 2026-10-17 | docs: README를 기술 면접용으로 개편 + 문서·ADR 점검 |
| [205](https://github.com/rndigkwk/dograg/pull/205) | 2026-10-18 | eval(report): 규칙 조정에 쓰지 않은 보고서 holdout 12문항 |
| [206](https://github.com/rndigkwk/dograg/pull/206) | 2026-10-18 | fix(report): 이름 없이 여러 보고서를 묻는 질문은 앞선 보고서 3개에서 각각 찾기 |
| [207](https://github.com/rndigkwk/dograg/pull/207) | 2026-10-18 | fix(ocr): KB 보고서 OCR 오인식 규칙 3개 추가 (data-v6) |
| [208](https://github.com/rndigkwk/dograg/pull/208) | 2026-10-18 | fix(report): 보호자 말을 보고서 용어로, 지목한 보고서는 그 안에서만 찾기 |
| [209](https://github.com/rndigkwk/dograg/pull/209) | 2026-10-18 | fix(report): h10 질문 말투 빼기, h08 OCR 숫자 손 정정 (data-v7) |
| [210](https://github.com/rndigkwk/dograg/pull/210) | 2026-10-18 | fix(report): 이름 없는 질문은 보고서 4개에서, KB 28쪽 OCR 정정 (data-v8) |
| [211](https://github.com/rndigkwk/dograg/pull/211) | 2026-10-18 | fix(search): 운영 보고서 키워드 검색을 PGroonga에서 메모리 안 BM25로 (h04) |
| [212](https://github.com/rndigkwk/dograg/pull/212) | 2026-10-19 | ops: 릴리스 점검 스크립트와 API 롤백 워크플로 |
| [213](https://github.com/rndigkwk/dograg/pull/213) | 2026-10-19 | ops: SLO 목표, 주간 확인, 실패 알림(이슈) |
| [214](https://github.com/rndigkwk/dograg/pull/214) | 2026-10-19 | eval: 치과 관련도 세트, 보고서 보류 문항, 범위 밖 라우팅, 월간 평가 점검 |
| [215](https://github.com/rndigkwk/dograg/pull/215) | 2026-10-19 | eval: 리랭킹 API 측정 스크립트 (키 대기) |
| [216](https://github.com/rndigkwk/dograg/pull/216) | 2026-10-19 | fix(health): 자료와 먼 건강 질문은 근거 평가 없이 보류 (유사도 하한 0.4) |
| [217](https://github.com/rndigkwk/dograg/pull/217) | 2026-10-19 | ci: 병합 조건 네 가지 (완전성·절대 하한·상대 하한·회귀) + 기준선 |
| [218](https://github.com/rndigkwk/dograg/pull/218) | 2026-10-19 | fix(search): 운영 건강 검색에서 PGroonga 빼기 (의미 검색만), 동점 규칙 유지 |
| [219](https://github.com/rndigkwk/dograg/pull/219) | 2026-10-19 | eval: 사람 판정 성적표, Cohere 리랭킹 측정(채택 안 함) |
| [220](https://github.com/rndigkwk/dograg/pull/220) | 2026-10-19 | ci(gate): 실패한 안정 문항은 2번 더 물어 흔들림과 회귀를 가르기 |
| [222](https://github.com/rndigkwk/dograg/pull/222) | 2026-10-19 | fix(health): 반려견이 아닌 동물의 건강 질문은 검색 전에 보류 |
| [223](https://github.com/rndigkwk/dograg/pull/223) | 2026-10-19 | fix(ops): 릴리스 점검이 커밋 안 된 새 파일은 무시 |
| [224](https://github.com/rndigkwk/dograg/pull/224) | 2026-10-19 | ci: 다른 동물 규칙(#222) 뒤 기준선 다시 만들기 — #222 다음에 병합 |
| [225](https://github.com/rndigkwk/dograg/pull/225) | 2026-10-19 | feat(web): 방문 준비 보고서 인쇄 · PDF로 저장 |
| [226](https://github.com/rndigkwk/dograg/pull/226) | 2026-10-19 | feat(visit-prep): 고른 지난 상담 노트를 방문 준비 보고서에 넣기 |
| [227](https://github.com/rndigkwk/dograg/pull/227) | 2026-10-19 | feat(visit-prep): 멈춘 보고서 이어서 만들기 |
| [228](https://github.com/rndigkwk/dograg/pull/228) | 2026-10-19 | feat(health): 동물사랑배움터 돌봄 지침으로 일상 관리 질문 답하기 |
| [229](https://github.com/rndigkwk/dograg/pull/229) | 2026-10-19 | fix(router): 노령·사망·이별 질문을 건강 상담으로 |
| [230](https://github.com/rndigkwk/dograg/pull/230) | 2026-10-19 | feat(visit-prep): 건강 조사원도 동물사랑배움터 돌봄 지침 찾기 |
| [231](https://github.com/rndigkwk/dograg/pull/231) | 2026-10-19 | feat(web): 관리 일정 — 지침 주기로 다음 예방·접종 날짜 알려 주기 |
| [232](https://github.com/rndigkwk/dograg/pull/232) | 2026-10-19 | feat(ops): 운영에서 돌봄 지침 사용 비율 재기 |
| [233](https://github.com/rndigkwk/dograg/pull/233) | 2026-10-19 | feat(data): 농식품부 여름나기 보도자료로 열사병 질문 답하기 |
| [234](https://github.com/rndigkwk/dograg/pull/234) | 2026-10-19 | docs: 지침 비용 측정 — 문맥 길이는 그대로 둠 |
| [235](https://github.com/rndigkwk/dograg/pull/235) | 2026-10-19 | fix(router): 이별 뒤 슬픔·사망 신고 질문도 건강 상담으로 |
| [236](https://github.com/rndigkwk/dograg/pull/236) | 2026-10-19 | fix(data): 지침 문맥을 문장 단위로, 리플릿 신고처 정리 |
| [238](https://github.com/rndigkwk/dograg/pull/238) | 2026-10-19 | feat(api): 모델 한도가 떨어지면 오류 대신 안내와 검색 결과 보여 주기 |
| [239](https://github.com/rndigkwk/dograg/pull/239) | 2026-10-19 | ci: 지침 검색·데이터 버전 변경에도 병합 게이트 돌리기 |
| [240](https://github.com/rndigkwk/dograg/pull/240) | 2026-10-20 | docs: 평가와 운영의 OpenAI 키 나누기 |
| [241](https://github.com/rndigkwk/dograg/pull/241) | 2026-10-20 | docs: README·개선 기록을 PR 240까지 갱신 (포트폴리오용) |
| [242](https://github.com/rndigkwk/dograg/pull/242) | 2026-10-20 | fix(streamlit): 백업 화면도 한도 소진 시 안내와 검색 결과 |
| [243](https://github.com/rndigkwk/dograg/pull/243) | 2026-10-20 | eval: 주간 회귀에 돌봄 지침 세트(16) 추가 |
| [244](https://github.com/rndigkwk/dograg/pull/244) | 2026-10-20 | fix(outage): 한도 안내에 화면마다 쓸 수 있는 기능만 적기 |
| [245](https://github.com/rndigkwk/dograg/pull/245) | 2026-10-20 | docs(adr): 0010 공공 돌봄 지침, 0011 모델 한도 소진 대응 |
| [246](https://github.com/rndigkwk/dograg/pull/246) | 2026-10-20 | fix(guides): 지침 기준 0.55 → 0.52 (g11 몸 만지기 교육) |
| [247](https://github.com/rndigkwk/dograg/pull/247) | 2026-10-20 | feat(visit-prep): 관리 일정의 기한 지난 항목을 방문 보고서 질문으로 |
| [248](https://github.com/rndigkwk/dograg/pull/248) | 2026-10-20 | ci: 병합 게이트 기준선 다시 만들기 (#246 코드 3회) |
| [249](https://github.com/rndigkwk/dograg/pull/249) | 2026-10-20 | ops: API 카나리 배포 — 트래픽 0%로 올려 검사한 뒤 넘기기 |
| [250](https://github.com/rndigkwk/dograg/pull/250) | 2026-10-20 | docs: 미해결 과제 정리 (예전 유사도 수치, 관련도 하한) |
| [251](https://github.com/rndigkwk/dograg/pull/251) | 2026-10-20 | docs(readme): 작업 방식과 AI 도구 사용 범위 |
| [252](https://github.com/rndigkwk/dograg/pull/252) | 2026-10-20 | eval: 주간 회귀에 Context Recall·Precision 기록 (교안 Day 59) |
| [253](https://github.com/rndigkwk/dograg/pull/253) | 2026-10-20 | fix(ops): 카나리 검사가 실패하면 배포 단계도 실패하게 (pipefail) |
| [255](https://github.com/rndigkwk/dograg/pull/255) | 2026-10-20 | feat(canary): Supabase 장애 주입 연습 + 채팅 고장 연습에서 나온 두 가지 수정 |
| [256](https://github.com/rndigkwk/dograg/pull/256) | 2026-10-20 | eval(retrieval): 기타 라벨 검색 품질 측정 (자료의 76.9%, 검증 0건) |
| [257](https://github.com/rndigkwk/dograg/pull/257) | 2026-10-20 | feat(places): 병원 목록 위에 그 지역 중간 진료비를 전국과 나란히 |
| [258](https://github.com/rndigkwk/dograg/pull/258) | 2026-10-20 | docs(cloud-run): Supabase 장애 연습 기록 + 마지막 트레이스 누락 발견 |
| [259](https://github.com/rndigkwk/dograg/pull/259) | 2026-10-20 | fix(tracing): API 응답이 끝나기 전에 Langfuse 기록을 보낸다 |
| [260](https://github.com/rndigkwk/dograg/pull/260) | 2026-10-20 | feat(tracing): 대체 경로로 답한 경우를 Langfuse에 WARNING으로 남긴다 |
| [261](https://github.com/rndigkwk/dograg/pull/261) | 2026-10-20 | feat(ops): 장애 로그가 남으면 이메일 알림 (Cloud Monitoring) |
| [262](https://github.com/rndigkwk/dograg/pull/262) | 2026-10-20 | feat(ops): API 로그를 JSON 한 줄로, 답변마다 요약 한 줄 (Cloud Logging) |
| [263](https://github.com/rndigkwk/dograg/pull/263) | 2026-10-20 | feat(canary): 건강 답변의 trace_id 출력 + Supabase 장애 연습 2회차 기록 |
| [264](https://github.com/rndigkwk/dograg/pull/264) | 2026-10-20 | ci(eval): 11월 6일까지 주간 회귀와 PR 게이트를 Langfuse 없이 실행 |
| [265](https://github.com/rndigkwk/dograg/pull/265) | 2026-10-20 | eval(rerank): GPU 리랭커 재검토용 Colab 노트북 + 운영 검색 순위 저장 |
| [266](https://github.com/rndigkwk/dograg/pull/266) | 2026-10-21 | eval(guardrails): 교안 day64 레드팀 24문항 추가 (측정 전에 작성) |
| [267](https://github.com/rndigkwk/dograg/pull/267) | 2026-10-21 | feat(guardrails): 위기 상담 번호를 맨 앞에, 검색 레일, 허용 밖 링크 제거 (교안 day64) |
| [268](https://github.com/rndigkwk/dograg/pull/268) | 2026-10-21 | feat(citations): 건강 답변에 문장별 [사례 n] 인용 + 숫자 출처 검사(모델 없음) |
| [269](https://github.com/rndigkwk/dograg/pull/269) | 2026-10-21 | eval(embedding): 하드 네거티브로 앱 임베딩을 다시 학습하는 Colab 노트북 (MLflow 기록) |
| [270](https://github.com/rndigkwk/dograg/pull/270) | 2026-10-21 | eval(router): 작은 분류기로 Decisions 호출을 대신할 수 있나 — 측정, 적용 안 함 |
| [271](https://github.com/rndigkwk/dograg/pull/271) | 2026-10-21 | docs: GPU 리랭커·하드 네거티브 임베딩 결과 (둘 다 미적용) |
| [272](https://github.com/rndigkwk/dograg/pull/272) | 2026-10-21 | docs: GPU 리랭커 할 일 항목을 결과로 바꿈 |
| [273](https://github.com/rndigkwk/dograg/pull/273) | 2026-10-21 | fix(streamlit): 근거 번호를 답의 [사례 n]·[지침 n]과 맞춤 |
| [274](https://github.com/rndigkwk/dograg/pull/274) | 2026-10-21 | ci: 가드레일 레드팀을 주간 회귀·가드레일 PR 게이트에, 레일 알림 2개 |
| [275](https://github.com/rndigkwk/dograg/pull/275) | 2026-10-21 | eval: NeMo Guardrails·Llama Guard 3·Prompt Guard 2를 레드팀 68문항으로 비교 (미적용) |
| [276](https://github.com/rndigkwk/dograg/pull/276) | 2026-10-22 | perf(health): 답변 생성 추론을 low로 (p90 18.5→11.4초, 사람 판정 6:5:11) |
| [277](https://github.com/rndigkwk/dograg/pull/277) | 2026-10-22 | fix(guardrails): 위기 표현 두 가지 추가 (다른 모델이 쓴 위기 문항 3개 중 2개를 놓침) |
| [278](https://github.com/rndigkwk/dograg/pull/278) | 2026-10-22 | eval: Claude를 두 번째 판사·레드팀 작성자로 (판사는 미채택, 레드팀이 위기 빈틈 발견) |
| [279](https://github.com/rndigkwk/dograg/pull/279) | 2026-10-22 | eval: 새 위기 holdout(0/5)과 답변 판정 기준 2·라벨 30칸 |
| [280](https://github.com/rndigkwk/dograg/pull/280) | 2026-10-22 | feat(guardrails): 위기 표현을 모델로도 판정 (정규식 0/5 → 12/12, 오탐 0/305) |
| [281](https://github.com/rndigkwk/dograg/pull/281) | 2026-10-23 | feat(health): 비용을 묻는 건강 질문에 진료비 안내 한 줄 (사용자 메모 h12) |
| [282](https://github.com/rndigkwk/dograg/pull/282) | 2026-10-23 | fix(guardrails): '저를 따라가고 싶은'은 반려견 이야기 — 위기 정규식 오탐 정리 |
| [283](https://github.com/rndigkwk/dograg/pull/283) | 2026-10-23 | ci: 레드팀 회귀 판정을 공격·위기 문항으로 한정, 정상 질문은 통과율로 |
| [284](https://github.com/rndigkwk/dograg/pull/284) | 2026-10-23 | feat: 옛 Streamlit 주소를 새 웹 앱 안내 페이지로 (P5) |
| [285](https://github.com/rndigkwk/dograg/pull/285) | 2026-10-23 | feat: Streamlit 화면을 새 웹 앱 안내로, 8시간 점검은 API·웹 앱으로 (P5) |
| [286](https://github.com/rndigkwk/dograg/pull/286) | 2026-10-23 | docs: 이번 주 결과를 README 핵심 지표와 개선 기록에 (10-21~23) |
| [287](https://github.com/rndigkwk/dograg/pull/287) | 2026-10-23 | ops: Cloud Run Streamlit 서비스 제거, 수동 배포·복구 안내서 |
| [289](https://github.com/rndigkwk/dograg/pull/289) | 2026-10-23 | perf(api): 시작 때 건강 검색 미리 읽기 |
| [290](https://github.com/rndigkwk/dograg/pull/290) | 2026-10-23 | eval: 답변 판사 기준 1·2를 60칸에서 재기 |
| [291](https://github.com/rndigkwk/dograg/pull/291) | 2026-10-23 | perf(web): 마크다운은 답이 올 때, 홈 사진은 보이는 크기로 |
| [292](https://github.com/rndigkwk/dograg/pull/292) | 2026-10-23 | ops: 모델 호출 제한 시간과 재시도 1번, 응답 없는 모델은 검색 결과로 |
| [293](https://github.com/rndigkwk/dograg/pull/293) | 2026-10-23 | docs(security): 최소 권한 점검과 남은 빈틈 2개 |
| [294](https://github.com/rndigkwk/dograg/pull/294) | 2026-10-23 | ci: 'Streamlit app checks'를 'Python tests'로 이름만 바꾸기 |
| [295](https://github.com/rndigkwk/dograg/pull/295) | 2026-10-23 | feat(rails): 레일 원본 파일과 규칙 id (교안 day64 레일 통합) |
| [296](https://github.com/rndigkwk/dograg/pull/296) | 2026-10-23 | feat(answer): 견종과 1~2살 나이 차이는 따지지 않기 |
| [297](https://github.com/rndigkwk/dograg/pull/297) | 2026-10-23 | fix(pii): 검사 수치·목록·범위를 주소로 가리던 오탐 고치기 (입력 레일 IN-01) |
| [298](https://github.com/rndigkwk/dograg/pull/298) | 2026-10-23 | feat(answer): 병원 권고는 끝에 한 번, 원인과 관리 요령 먼저 |
| [299](https://github.com/rndigkwk/dograg/pull/299) | 2026-10-23 | docs(wiki): 답변 판사 기준 2와 사람 라벨 60칸 결과 |
| [300](https://github.com/rndigkwk/dograg/pull/300) | 2026-10-23 | fix(web): 보조 글자 대비와 채팅 첫 화면 흔들림 (Lighthouse) |
| [301](https://github.com/rndigkwk/dograg/pull/301) | 2026-10-23 | feat(web): 대기 화면(경과 시간·서버 깨우는 중·멈추기)과 오류 화면(원인별 문구·다시 시도) |
| [302](https://github.com/rndigkwk/dograg/pull/302) | 2026-10-23 | feat(web): 리디자인 1단계 — 메뉴 4묶음(휴대폰 하단 탭), A안 청록 색, 선 아이콘 |
| [303](https://github.com/rndigkwk/dograg/pull/303) | 2026-10-23 | feat(web): 리디자인 2단계 — 홈은 질문창 먼저, 바로가기 4개 |
| [304](https://github.com/rndigkwk/dograg/pull/304) | 2026-10-23 | feat(web): 리디자인 3단계 — 화면 안의 이모지를 선 아이콘으로 |
| [305](https://github.com/rndigkwk/dograg/pull/305) | 2026-10-23 | feat(web): 리디자인 4단계 — 진료비 시·도 차트를 점 그래프로 |
