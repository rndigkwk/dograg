# 배포 서버 자원 (메모리)

Streamlit Community Cloud는 앱 하나에 **메모리 최대 2.7GB**, **CPU 최대 2코어**를 준다([공식 문서](https://docs.streamlit.io/deploy/streamlit-community-cloud/manage-your-app)). 한도를 넘으면 앱이 "Oh no." 오류 화면으로 멈춘다. 새 모델이나 색인을 추가할 때마다 이 페이지 기준으로 확인한다.

## 측정 방법 (2026-10-02)

- 실행: `uv run python scripts/measure_memory.py [--reranker qwen3|bge-dense]` → `output/memory_*.json`
- 앱과 같은 로더(`pages.rag`의 `load_vector_db`, `load_health_bm25_index`, `load_report_vector_db`)를 단계별로 불러오며 프로세스 RSS를 기록했다. Chroma는 임시 복사본을 썼다.
- torch를 2스레드로 제한해 Cloud의 2코어를 흉내 냈다.
- **한계:**
  - Windows 로컬에서 측정했다. Linux 배포 서버와는 수십~수백MB 차이가 날 수 있다.
  - 두 측정을 동시에 돌려서 **지연 시간은 실제보다 부풀려졌을 수 있다.** 메모리 값은 영향을 받지 않는다.

## 결과

| 단계 (누적) | RSS | 증가 |
| --- | ---: | ---: |
| 라이브러리 import (streamlit, langchain, torch) | 367MB | |
| + 건강 Chroma + `ko-sroberta-multitask` | 985MB | +618 |
| + BM25 색인 (Kiwi, 19,206건) | 1,702MB | +717 |
| + 보고서 Chroma + `bge-m3` | **3,195MB** | **+1,493** |

리랭커를 위 상태 위에 추가했을 때:

| 리랭커 | 최종 RSS | 최고치 | 질문당 리랭킹 시간 (후보 24건) |
| --- | ---: | ---: | ---: |
| 이미 올라간 `bge-m3`로 다시 점수 매기기 | 3,795MB | 3,908MB | 45초 ~ 145초 |
| `Qwen3-Reranker-0.6B` (CrossEncoder) | 3,379MB | **5,114MB** | **13분 ~ 19분** |

## 해석

1. **리랭커 없이도 이미 한도를 넘는다.** 건강 질문 뒤에 보고서 질문이 들어오면 bge-m3가 올라가서 약 3.2GB가 된다. 배포 앱이 지금 버티는 건 모델을 처음 쓰일 때 불러오기 때문으로 추정한다. 보고서 질문이 한 번이라도 들어오면 한도에 걸릴 가능성이 높다. **배포 앱에서 직접 확인하지는 않았다.** 확인하면 실제 사용자에게 오류 화면이 보일 수 있어서다.
2. **bge-m3가 가장 큰 원인이다(약 1.5GB).** 보고서 127청크를 검색하려고 건강 Q&A 전체용 모델보다 큰 모델을 하나 더 들고 있는 셈이다.
3. **로컬 리랭커는 Cloud CPU에서 쓸 수 없다.** 앞서 [lecture-review.md](lecture-review.md)에서 "bge-m3 재사용이 부담을 줄인다"고 예상했지만, 메모리 +600MB에 질문당 수십 초가 걸려 틀린 예상이었다. Qwen3는 메모리와 속도 모두 불가능한 수준이다.
4. **보고서 PDF 추가 자체는 부담이 작다.** `data/source/`의 PDF 4개를 더해도 약 1,000청크, 벡터는 약 4MB 증가로 추정된다. 기존 보고서는 실제 127청크인데 같은 방법으로 128청크로 추정돼 방법은 믿을 만하다. 문제는 데이터가 아니라 임베딩 모델이다.

## OpenAI 임베딩 전환 후 재측정 (2026-10-04)

앱의 건강·보고서 컬렉션을 모두 OpenAI `text-embedding-3-small`로 바꾼 상태에서 다시 측정했다(`output/memory_openai_baseline.json`).

| 단계 (누적) | 전환 전 | 전환 후 |
| --- | ---: | ---: |
| import | 367MB | 367MB |
| + 건강 Chroma + 임베딩 | 985MB | **574MB** |
| + BM25 색인 | 1,702MB | 1,339MB |
| + 보고서 Chroma + 임베딩 | 3,195MB | **1,351MB** (최고 1,356MB) |

- 한도 2.7GB 대비 약 1.35GB의 여유가 생겼다.
- **그러나 건강 검색 품질이 떨어졌다**([retrieval-experiments.md](retrieval-experiments.md) 실험 5). 건강만 ko-sroberta로 되돌리면 약 **1.76GB**로 추정된다(전환 전 ko-sroberta 단계 +618MB와 OpenAI 단계 +207MB의 차이를 더한 값). 이 구성도 한도 안이다.
- **torch는 여전히 메모리에 올라온다.** 앱 코드가 아니라 `langchain_core`가 `transformers`가 설치돼 있으면 토크나이저용으로 import하고, 그때 torch가 함께 로드된다. 배포 의존성에서 `sentence-transformers`, `langchain-huggingface`(그리고 이들이 끌어오는 `transformers`, `torch`)를 빼면 수백MB를 더 줄이고 설치 시간도 줄일 수 있다. 다만 노트북과 일부 실험 스크립트가 같은 `pyproject.toml`을 쓰므로, 앱용과 실험용 의존성을 나누는 작업이 필요하다. 건강을 ko-sroberta로 되돌리면 이 의존성은 남겨야 한다.

## 최종 구성: 건강 ko-sroberta + 보고서 OpenAI (2026-10-04 적용)

실측(`output/memory_mixed_ko_openai.json`): import 368MB → 건강 Chroma + ko-sroberta 989MB → BM25 1,697MB → 보고서 Chroma + OpenAI **1,765MB**(최고치 동일). 한도 2.7GB 안이다. 전환 전 3,195MB보다 1.4GB 적다.

## 저장소 크기: 왜 이렇게 늘었나 (2026-10-04 분석)

`data/chroma_db`는 git이 추적한다(`chroma.sqlite3`만 Git LFS). git이 보여주는 sqlite는 LFS 포인터라서 실제 크기가 아니다. 원래 sqlite는 **183.5MB**였다(LFS 기록 192,430,080바이트).

| 시점 | 전체 | sqlite | 벡터 파일 |
| --- | ---: | ---: | --- |
| 원본 (`dograg_backup`) | 244MB | 183.5MB | ko 건강 59MB, bge-m3 보고서 등 |
| GPT 적재 후 (컬렉션 5개) | 681MB | 503.1MB | + OpenAI 건강 110MB, OpenAI 보고서 6MB |
| 컬렉션 정리 후 | 268.5MB | 202.7MB | ko 건강 59MB, OpenAI 보고서 6MB |
| **`qa.output` 제거 후 (현재)** | **209.2MB** | **143.4MB** | 동일 |

### 늘어난 437MB의 내역

| 원인 | 증가량 | 설명 |
| --- | ---: | --- |
| **메타데이터 표와 색인** | **+282MB** | 아래 참고. 가장 큰 원인 |
| OpenAI 건강 벡터 파일 | +110MB | 1536차원이라 768차원(ko)보다 2배 크다. 19,206건 × 1536 × 4바이트 + HNSW 링크 |
| 전문 검색(FTS) 색인 | +42MB | Chroma는 모든 문서 본문을 SQLite FTS로 자동 색인한다. 건강 질문 19,206건이 한 번 더 들어갔다 |
| `embeddings_queue` 등 | +약 20MB | Chroma 내부 쓰기 기록과 ID 색인 |
| 원본의 빈 페이지 | −19MB | 원본은 VACUUM 전이라 빈 공간 19.4MB가 있었다 |

### 메타데이터가 8배로 부풀어 오른 이유

- OpenAI 건강 컬렉션의 메타데이터 **원문은 34.2MB**였다. 그중 `source_record_json`(16.6MB)은 CSV 한 행 전체(질문, 답변, 지시문)를 JSON으로 통째로 넣은 것이고, `qa.output`(7.2MB)은 답변 원문이다. 같은 질문·답변이 문서 본문, `qa.output`, `source_record_json`에 세 번 저장됐다.
- Chroma는 **모든 문자열 메타데이터 값을 SQLite B-tree 색인(`embedding_metadata_string_value`)에 그대로 넣는다.** 필터 검색을 위해서인데, 긴 문장도 예외가 아니다. 그래서 긴 텍스트는 표 한 번, 색인 한 번, 최소 두 번 저장된다.
- 긴 값은 SQLite 페이지 하나에 들어가지 않아 넘침(overflow) 페이지로 쪼개지고, 각 페이지의 남는 공간이 낭비된다.
- 결과적으로 원문 34MB가 디스크에서 약 274MB(표 +103MB, 색인 +171MB)가 됐다. **약 8배**다.
- 기존 `pet_care`도 답변 원문(`qa.output`)을 메타데이터에 넣고 있었다. 이 키를 지우자 sqlite가 **59MB** 줄었다(202.7 → 143.4MB). 처음에 "100MB 이상"으로 예상했지만, 실제 절감은 그보다 작았다. 문서 본문(질문)도 Chroma 내부에서 문자열 메타데이터와 FTS로 저장돼 남아 있기 때문이다.

### 정리한 내용

1. 앱이 쓰지 않는 컬렉션 3개(OpenAI 건강, 빈 `pet_analysis`, bge-m3 `pet_analysis_1024`)를 삭제했다. Chroma가 남긴 벡터 폴더 3개도 지웠다. 정리 전 전체 백업은 `output/chroma_backup_before_cleanup_20261004/`(git 미추적)에 있다.
2. VACUUM을 했다. 이제 100MB를 넘는 일반 파일은 없다. sqlite(202.7MB)는 LFS로 올라간다.

### 앞으로 지킬 것

- **긴 텍스트를 메타데이터에 넣지 않는다.** 원본 레코드 JSON 같은 추적 정보는 sha256과 행 번호만 넣고, 원문은 CSV에서 다시 찾는다.
- **(2026-10-04 적용)** 건강 답변은 `pet_care`의 문서 ID(= `data/df.csv`의 행 번호)로 CSV에서 읽는다(`src/health_answers.py`). 19,206건 모두 ID와 질문·답변이 일치함을 확인했다(CSV의 `
`만 제거). 답변 표는 메모리 약 19MB, 로딩 0.45초다. 지우기 전 DB는 `output/chroma_backup_before_qa_strip_20261004/`에 있다.
- 새 컬렉션을 만들면 쓰지 않게 된 컬렉션은 지우고 VACUUM한다. 컬렉션을 지워도 벡터 폴더가 남을 수 있으니 확인한다.
- LFS 무료 한도는 Streamlit Cloud가 배포할 때마다 sqlite를 내려받으면서 소모된다. 정확한 한도는 확인이 필요하다.

## 권장 조치

| 조치 | 예상 절감 | 비고 |
| --- | ---: | --- |
| **보고서 임베딩을 OpenAI 임베딩 API로 교체 (권장)** | 약 1.5GB | 로컬 모델이 없어진다. 보고서 분석은 이미 OpenAI 키가 있어야 답하므로 새 의존성이 아니다. 대신 질문마다 외부 API를 호출하고 비용이 조금 든다. |
| 보고서 임베딩을 `ko-sroberta`로 통일 | 약 1.5GB | **주의:** `ko-sroberta-multitask`는 최대 **128토큰**만 읽는다. 현재 보고서 청크는 중앙값 459토큰이고 127개 중 117개가 128토큰을 넘어, 그대로 쓰면 청크 앞부분만 임베딩된다(2026-10-03 확인). 쓰려면 청크를 약 250자로 다시 나눠야 한다. |
| 또는 bge-m3를 fp16으로 로드 | 약 0.7GB 추정 | 측정하지 않았다. |
| BM25 색인 경량화(희소 행렬 기반 `bm25s` 등) | 일부 | 측정하지 않았다. 지금 약 0.7GB다. |
| 리랭킹을 로컬 모델 대신 LLM 근거 판정으로 대체 | 모델 추가 없음 | CRAG의 근거 평가 호출이 리랭킹 역할을 겸할 수 있다. 소형 다국어 Cross-Encoder(약 100MB급)는 측정하지 않았다. |

**결론:** 리랭킹이나 PDF 추가보다 먼저 **임베딩 모델을 하나로 줄이는 작업**이 필요하다. 그래야 현재 앱도 한도 안에 들어오고, 이후 기능을 넣을 여유가 생긴다.

## 첫 질문 대기 시간 (2026-10-05)

배포 앱이 깨어난 뒤 첫 건강 질문에 약 2분이 걸렸다. 면접관이 링크를 열고 처음 던지는 질문이므로 우선 고쳤다.

**어디서 시간이 드는가 (로컬 측정)**
| 단계 | 시간 |
| --- | ---: |
| **BM25용 문서 토큰화 (Kiwi, 19,206건)** | **130.6초** |
| ko-sroberta 로딩과 첫 검색 | 16.6초 |
| 페이지 import | 15.8초 |
| Chroma 문서 읽기, Kiwi 초기화, BM25 구축 | 약 2.5초 |

**고친 것**
1. **토큰 캐시** (`data/bm25_health_tokens.json.gz`, 1.72MB, `scripts/build_bm25_cache.py`로 생성)
   - 문서 ID와 본문의 해시, 토크나이저 버전을 함께 저장한다. 데이터나 토크나이저가 바뀌면 캐시를 무시하고 직접 토큰화하므로, 오래된 캐시를 쓰는 일은 없다.
   - 앱은 캐시를 읽기만 하고 쓰지 않는다.
   - 색인 준비 시간이 132.8초에서 **2.2초**가 됐다. 검증 질문 200개에서 직접 토큰화한 색인과 BM25 상위 12건 결과가 **모두 같았다.**
2. **백그라운드 워밍업**
   - 페이지가 열리면 서버 프로세스당 한 번, ko-sroberta 모델, BM25 색인, 답변 표를 백그라운드에서 미리 불러온다(`start_warmup`).
   - 테스트(AppTest)와 CI에서는 돌지 않는다. 처음에는 `sys.argv`로 `streamlit run`을 판별했는데, Streamlit이 앱을 실행할 때 `sys.argv`를 `["main.py"]`로 바꿔서 실제 서버에서도 워밍업이 꺼져 있었다. 측정으로 발견했다. 지금은 "Streamlit 런타임이 있고 `streamlit.testing`이 로드되지 않았을 때"로 판별한다. `DOGRAG_WARMUP=0/1`로 직접 켜고 끌 수 있다.

**결과 (로컬, 서버를 새로 띄운 직후 첫 질문)**
| | 첫 질문까지 |
| --- | ---: |
| 이전 | 약 165초 이상 (배포 앱에서 약 2분) |
| 토큰 캐시만 적용, 페이지 연 지 25초 만에 질문 | 23초 (워밍업이 아직 진행 중) |
| **토큰 캐시 + 워밍업, 페이지에 1분 머문 뒤 질문** | **8초** |
| 참고: 두 번째 질문 | 6초 |

배포 앱(Streamlit Cloud)에서의 측정은 병합 후 확인이 필요하다. 앱이 잠자기 상태라면 깨우는 시간은 여전히 별도로 든다.

## 메모리 초과 경고 대응 (2026-10-05)

PR #6 병합 후 Streamlit에서 "It's using too much memory!" 메일이 왔다(한도 2.7GB).

**어디에 쓰이나 (로컬 Windows, `scripts/measure_memory.py`)**
| 단계 | 누적 RSS | 증가 |
| --- | ---: | ---: |
| import (streamlit, langchain, torch) | 374MB | 374MB |
| + 건강 Chroma + ko-sroberta | 994MB | 620MB |
| + BM25 색인 (Kiwi 포함) | 1,508MB | 514MB |
| + 보고서 Chroma (OpenAI) | 1,573MB | 65MB |
| 질의 3건 후 최대 | 1,817MB | |

Kiwi 형태소 분석기 하나가 약 480MB였다. BM25 색인 자체(rank_bm25)는 약 110MB다.

**조치**
1. **Kiwi 다어절 사전 끄기** (`Kiwi(load_multi_dict=False)`): Kiwi가 482MB에서 294MB로 줄었다. 19,206개 문서 중 173개(0.9%)만 토큰이 달라졌다(사전에 붙어 있던 다어절 명사가 단어 단위로 나뉨). 검증 질문 561개에서 하이브리드 hit@3은 **0.262로 같았고** MRR@3은 0.184에서 0.185가 됐다(순위가 바뀐 질문 1개). 토크나이저 버전을 `kiwi-nouns-sl-sn-v2`로 올리고 토큰 캐시를 다시 만들었다.
2. **스레드와 malloc arena 제한** (`src/memory_limits.py`, `main.py` 맨 위에서 호출):
   - Cloud 컨테이너는 호스트의 CPU 수를 보여 주므로 torch와 BLAS가 코어 수만큼 스레드를 만든다. 로컬에서도 스레드가 125개까지 늘었다. `OMP/MKL/OPENBLAS_NUM_THREADS=2`로 묶었다. CPU는 2코어라서 속도 손해는 없다.
   - Linux(glibc)는 바쁜 스레드마다 malloc arena를 따로 만들어서 RSS가 실제 사용량보다 커진다. `mallopt(M_ARENA_MAX, 2)`로 제한한다. 환경 변수 `MALLOC_ARENA_MAX`는 프로세스가 시작될 때만 읽히므로 Python 안에서 설정하면 효과가 없다. 그래서 `ctypes`로 직접 호출한다.
   - 워밍업이 끝나면 `malloc_trim(0)`으로 로딩 중 잠깐 쓴 메모리를 OS에 돌려준다.

**결과 (로컬)**: 최대 메모리가 1,817MB에서 **1,587MB**로 줄었다(−230MB). 이 수치는 1번만 반영한 것이다. 2번은 Linux에서만 효과가 있어서 로컬에서는 측정할 수 없고, 배포 앱에서 확인해야 한다.

남은 큰 항목은 ko-sroberta(약 620MB, fp32)다. 더 줄여야 하면 다음 후보는 모델 양자화나 ONNX 변환이다. 둘 다 검색 품질을 다시 평가해야 한다.
