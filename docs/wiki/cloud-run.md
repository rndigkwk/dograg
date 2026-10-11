# Cloud Run 배포 (2026-10-11 시작)

Streamlit Community Cloud에 더해 Google Cloud Run에도 같은 저장소의 앱을 띄운다. 계획은 Cloud Run을 주 배포로, Streamlit Cloud를 예비로 두는 것이다.

## 1단계: 컨테이너 이미지 (로컬 측정)

**파일**
- `Dockerfile`: python 3.12-slim + uv로 잠금 파일 그대로 설치한다. torch는 설치하지 않는다.
- `.dockerignore`
- `scripts/prefetch_image_assets.py`

**빌드와 실행**

```bash
docker build --secret id=hf_token,env=HF_TOKEN -t ragdog .
docker run --rm -p 8080:8080 --memory=2g --env-file <키만 담은 파일> ragdog
```

**설계**
- **비공개 데이터와 모델을 이미지에 넣는다.**
  - 앱은 원래 시작할 때 비공개 HF 데이터셋(`data-v3`, 이미지 안 254MB)과 미세조정 ONNX 모델을 내려받는다.
  - Cloud Run은 실행 중에 쓴 파일이 메모리를 차지하고, 새로 켜질 때마다 다시 받아야 한다.
  - 그래서 빌드 단계에서 받아 둔다. 데이터는 `src/private_data.py`의 리비전이 바뀔 때만 다시 받는다(별도 레이어).
  - 실행 중에는 `HF_HUB_OFFLINE=1`로 허브에 접속하지 않는다.
- **HF 토큰은 BuildKit 비밀 값으로만 넘긴다.** 이미지 레이어와 기록에 남지 않는다. 이미지 안에서 `HF_TOKEN` 환경 변수, `.env`, `.streamlit/secrets.toml`이 모두 없음을 확인했다.
- **이미지는 비공개 저장소에만 올린다.** AI Hub 데이터에서 나온 파일이 들어 있으므로 Artifact Registry 같은 비공개 저장소에만 올리고, Docker Hub 같은 공개 저장소에는 올리지 않는다.
- **`RAGDOG_CONTAINER=1`로 배포 환경임을 알린다.** 그러면 `settings.deployed()`가 참이 된다. 로컬처럼 Chroma 폴더(177MB)를 `output/`에 복사하지 않고, Langfuse 환경은 `production`이 된다. 로컬 컨테이너 시험에서는 `LANGFUSE_TRACING_ENVIRONMENT=development`로 덮어썼다.

**측정 (Docker Desktop, 컨테이너 제한 2GB·CPU 1개, 2026-10-11)**

| 항목 | 결과 |
| --- | --- |
| 이미지 크기 | 2.75GB (패키지 1.3GB, 데이터 254MB, 모델 179MB) |
| 첫 빌드 | 2분 56초 (코드만 바뀌면 의존성·데이터 레이어는 다시 쓰고, 시간은 재지 않았다) |
| 헬스 체크(`/_stcore/health`) 200 | 컨테이너 시작 직후 |
| 대기 중 메모리 | 65MB |
| 첫 페이지 표시 | 4.2초 |
| 첫 질문 답변(모델·색인 로딩 포함) | 18.2초 |
| 두 번째 건강 질문 / 시설 질문 | 3.6초 / 바로 |
| 질문 3개 뒤 메모리 | 1,024MiB |
| 방문 보고서 실행 중 최고 메모리(2초 간격 표본) | 1.06GiB |
| 방문 보고서 | 90초, 검수 통과 |

- **메모리:** 2GiB면 여유가 있다. Cloud Run 인스턴스는 2GiB로 시작한다.
- **방문 보고서에서 본 것:** 진료비 조사원이 `incomplete: max_messages`로 답 없이 끝났다. 다시 물었는데도 또 답이 없어, `NoAnswer`로 기록되고 기본 안내로 대신했다. #86의 재질문이 한 번으로는 부족한 경우가 있다는 뜻이다. 컨테이너와는 관계없는 API 응답 문제이고 따로 다룬다.

## 2단계: GitHub Actions로 빌드와 배포

**준비 (한 번만):**
1. Cloud Shell에서 `scripts/gcp/setup_cloud_run.sh`를 실행한다. 다시 실행해도 이미 만든 것은 그대로 둔다. 만드는 것:
   - 비공개 Artifact Registry 저장소(`ragdog`, 서울). 최신 이미지 3개만 남긴다.
   - 서비스 계정 두 개
     - `ragdog-runtime`: 앱이 실행되는 계정. 비밀 값 읽기만 한다.
     - `github-deployer`: 이미지를 올리고 배포하는 계정.
   - Workload Identity 풀과 공급자. **이 저장소(`rndigkwk/dograg`)의 Actions만** 쓸 수 있다.
   - Secret Manager 비밀 값 3개: `OPENAI_API_KEY`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`. 값은 화면에 보이지 않게 입력받는다.
2. 스크립트가 마지막에 출력한 `WORKLOAD_IDENTITY_PROVIDER` 값을 GitHub 저장소 변수 `GCP_WORKLOAD_IDENTITY_PROVIDER`에 넣는다. 비밀 값이 아닌 식별자다.

**배포** (`.github/workflows/deploy-cloud-run.yml`)
- main에 병합될 때마다 다음 순서로 돈다.
  1. 이미지를 빌드한다. HF 토큰은 저장소 비밀 값을 빌드에만 쓴다.
  2. `IMAGE:<커밋>`으로 이미지를 올린다.
  3. `gcloud run deploy`로 배포한다.
  4. `/_stcore/health`가 200을 줄 때까지 확인한다.
- 저장소 변수가 없으면 이 작업은 실패하지 않고 건너뛴다.

**Cloud Run 설정과 이유**

| 설정 | 값 | 이유 |
| --- | --- | --- |
| 메모리 / CPU | 2GiB / 1 | 측정 최고 1.06GiB |
| 최소 / 최대 인스턴스 | 0 / 2 | 쓰지 않을 때 요금 없음. 최대 2개가 비용 상한 |
| session affinity | 켬 | 방문 보고서의 되묻기 단계는 멈춘 실행을 서버 메모리에 둔다. 같은 브라우저는 같은 인스턴스로 보내야 한다 |
| 요청 시간 제한 | 3600초 | Streamlit은 탭마다 웹소켓을 열어 둔다 |
| CPU boost | 켬 | 새로 켜질 때 모델·색인 로딩을 빠르게 |
| Langfuse 환경 | `cloudrun` | Streamlit Cloud(`production`)와 트레이스를 나눠 본다 |

## 다음 단계
- 첫 배포 뒤 Streamlit Cloud와 시작 시간·응답 시간을 비교한다.
- 배포 점검 워크플로를 두 주소로 늘리고, README에 두 배포의 역할과 비용을 적는다.
