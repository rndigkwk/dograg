# 수동 배포·복구 안내서 (사람이 직접 할 때)

Claude Code 없이도 배포를 확인하고, 다시 배포하고, 되돌리고, 장애 때 대비 화면으로 옮길 수 있도록 정리한 문서다. 명령은 이 PC의 PowerShell 또는 구글 클라우드 Cloud Shell(bash)에서 그대로 붙여 넣으면 된다. 비밀 값(키, 토큰)은 화면에 출력하지 않는다.

## 0. 어디에 무엇이 떠 있나

| 구성 | 어디 | 주소 / 이름 | 배포 방식 |
| --- | --- | --- | --- |
| 웹 화면 | Vercel | <https://ragdog-rndigkwks-projects.vercel.app> | main에 `web/`가 바뀌면 Vercel이 자동 배포 |
| API | Google Cloud Run (서울) | 서비스 `ragdog-api`, <https://ragdog-api-892238791473.asia-northeast3.run.app> | main 병합 → GitHub Actions "Deploy to Cloud Run" |
| 데이터베이스·로그인 | Supabase | 무료 플랜 프로젝트 | 직접 관리(대시보드) |
| 대비 화면 | Streamlit Community Cloud | <https://dograg-hsckizrbd7fddwtv8mt7cs.streamlit.app>, 브랜치 `streamlit-backup` | 평소엔 "새 주소 안내"만 보여 줌. 장애 때 전체 화면으로 전환(5절) |

- 구글 클라우드 프로젝트: `ragdog-511311`, 지역 `asia-northeast3`
- 이미지 저장소: `asia-northeast3-docker.pkg.dev/ragdog-511311/ragdog/app:<커밋>`
- 2026-10-23까지 있던 Cloud Run Streamlit 서비스(`ragdog`)는 지웠다. 이 저장소의 화면은 웹(Vercel) 하나다.

## 1. 평소 흐름

1. 작업 브랜치에서 PR을 연다 → GitHub Actions가 단위 테스트(`Python tests`, `Web CI`)와, 답변 경로·가드레일을 바꾼 PR이면 실제 모델로 `PR quality check`를 돌린다.
2. 모두 초록이면 병합한다.
3. main 병합 → "Deploy to Cloud Run"이 이미지를 만들고 새 API를 **트래픽 0%로** 올린다 → 카나리 검사 4개(health·표·날짜 질문·건강 질문) → 통과하면 트래픽을 옮긴다. 웹은 Vercel이 따로 배포한다.
4. 확인: GitHub → Actions → "Deploy to Cloud Run"의 최근 실행이 초록이고, 요약(Summary)에 `ok   health`, `ok   chat rag` 줄이 보이면 된다.

## 2. 지금 상태 확인하기

PowerShell:

```powershell
Invoke-RestMethod https://ragdog-api-892238791473.asia-northeast3.run.app/health
```

- `status: ok`와 `commit`(지금 서비스 중인 커밋)이 나오면 API는 살아 있다. 커밋이 GitHub main의 최신 병합 커밋과 같으면 최신이 배포된 것이다.
- 더 자세히(답변까지): 저장소 폴더에서 아래를 실행한다. 모델을 약 4번 부른다.

```powershell
uv run python scripts/canary_check.py https://ragdog-api-892238791473.asia-northeast3.run.app
```

- `ok` 네 줄이 나오면 정상이다. `FAIL`이면 그 줄의 이유를 본다.
- 8시간마다 도는 점검을 지금 돌리려면: GitHub → Actions → "Keep deployed app awake and working" → Run workflow.

## 3. 다시 배포하기

### 3-1. 같은 코드를 다시 배포 (가장 흔함)

GitHub 웹: Actions → **Deploy to Cloud Run** → Run workflow → `fault`는 **none** 그대로 → Run.

PowerShell(GitHub CLI):

```powershell
gh workflow run deploy-cloud-run.yml --repo rndigkwk/dograg
```

```powershell
gh run list --workflow deploy-cloud-run.yml --repo rndigkwk/dograg --limit 1
```

- 10~15분 걸린다. 카나리가 실패하면 트래픽은 **이전 버전에 그대로** 남고, 실패 이슈가 자동으로 열린다(서비스는 멈추지 않는다).
- `fault`의 `chat`·`supabase`는 고장 연습용이다. 평소에는 고르지 않는다.

### 3-2. 웹 화면(Vercel) 다시 배포

Vercel 대시보드 → 프로젝트 `ragdog` → Deployments → 최신 배포의 ⋮ → **Redeploy**. 직전 배포로 되돌리려면 잘 되던 배포의 ⋮ → **Promote to Production**(즉시 바뀜).

## 4. 되돌리기 (새 버전이 이상할 때)

### 4-1. API를 이전 버전으로 (빌드 없이 몇 초)

GitHub 웹: Actions → **Roll back the API** → Run workflow.
- `revision`을 비워 두면 직전 버전으로 간다.
- 다시 최신으로 돌리려면 `to_latest`를 체크한다.

PowerShell:

```powershell
gh workflow run rollback-api.yml --repo rndigkwk/dograg
```

- 롤백은 트래픽을 고정한다. 다음 "Deploy to Cloud Run"이 성공하면 자동으로 새 버전으로 넘어간다.

### 4-2. GitHub Actions가 안 될 때 (Cloud Shell)

<https://console.cloud.google.com> → 오른쪽 위 Cloud Shell 아이콘. 저장소가 없어도 된다.

```bash
gcloud config set project ragdog-511311
```

```bash
gcloud run revisions list --service ragdog-api --region asia-northeast3 --limit 5
```

목록에서 잘 되던 버전 이름(예: `ragdog-api-00123-abc`)을 골라 트래픽을 옮긴다.

```bash
gcloud run services update-traffic ragdog-api --region asia-northeast3 --to-revisions=ragdog-api-00123-abc=100
```

이미 만들어 둔 이미지(커밋별로 저장돼 있음)로 다시 배포할 수도 있다. 이미지만 바꾸고 나머지 설정(비밀 값, 메모리 등)은 그대로 둔다.

```bash
gcloud run deploy ragdog-api --region asia-northeast3 --image=asia-northeast3-docker.pkg.dev/ragdog-511311/ragdog/app:<커밋 전체 해시>
```

## 5. 장애별 대응

| 증상 | 알림 | 원인과 할 일 |
| --- | --- | --- |
| 답변 대신 "모델 한도" 안내와 검색 결과만 나옴 | 메일 "model out of quota" | OpenAI 사용 한도 소진. platform.openai.com → Billing에서 한도를 올리거나 충전한다. 앱은 그동안 검색 결과만 보여 준다(멈추지 않음) |
| 답변이 느리거나 일부 목록이 비어 있음 | 메일 "Supabase unavailable" | Supabase 장애나 휴면. 앱은 로컬 검색으로 버틴다. Supabase 대시보드에서 프로젝트 상태를 보고, Paused면 Restore를 누른다 |
| 답변이 오류로 끝남 | 메일 "answers failing" | 메일의 시간에 Cloud Run 로그를 본다(Cloud Console → Cloud Run → ragdog-api → 로그). 새 배포 직후라면 4-1로 되돌린다 |
| 웹 화면이 안 열림 | — | Vercel 상태와 배포를 본다. 3-2로 직전 배포를 Promote한다 |
| 구글 클라우드 전체 장애나 요금 문제로 API를 못 씀 | — | 아래 "Streamlit 대비 화면으로 전환" |
| 주간 회귀·SLO 보고가 실패 | GitHub 이슈 자동 생성 | 이슈에 실패한 지표가 적혀 있다. 운영 장애가 아니라 품질 신호다. 급하지 않다 |

### Streamlit 대비 화면으로 전환 (구글 클라우드를 못 쓸 때)

`streamlit-backup` 브랜치는 2026-10-15 상태로 고정된 전체 앱이다. 검색은 자체 Chroma로 해서 **구글 클라우드에 기대지 않는다.** OpenAI 키는 필요하다.

1. <https://share.streamlit.io>에 로그인 → 앱 목록에서 `dograg-hsckizrbd7fddwtv8mt7cs` → ⋮ → **Settings → Secrets**.
2. 이미 있는 값(`OPENAI_API_KEY`, `HF_TOKEN` 등)은 그대로 두고 맨 아래에 한 줄을 더한 뒤 Save:

   ```toml
   STREAMLIT_FULL_APP = "1"
   ```

3. 앱이 다시 시작된다(안 되면 ⋮ → **Reboot app**). 첫 방문 때 상담 데이터를 내려받느라 몇 분 걸린다(`HF_TOKEN` 필요). 잠들어 있으면 "Yes, get this app back up"을 누른다.
4. 사용자에게 <https://dograg-hsckizrbd7fddwtv8mt7cs.streamlit.app> 를 안내한다.
5. 복구되면 그 한 줄을 지우고 Save → 다시 "새 주소 안내"만 보여 준다.

**대비 화면의 한계:** 10-15 이후 기능은 없다. 로그인·대화 저장, 위기 표현 모델 판정(10-22), 문장 인용(10-21), 진료비 안내 한 줄(10-23) 등이 빠져 있다. 위기 표현 안내도 없으니 장애가 길어지면 이 브랜치를 main에 맞춰 올리는 작업(코드 작업)이 필요하다.

## 6. 정기 작업과 알림

| 워크플로 | 언제 | 실패하면 |
| --- | --- | --- |
| Keep deployed app awake and working | 8시간마다 | API 카나리 4개와 웹 페이지 6개를 본다. 실패하면 2절로 상태를 확인하고 3·4절로 대응 |
| Weekly regression evaluation | 매주 월요일 09:23 | 품질 지표 실패. 이슈를 보고 원인 PR을 찾는다(모델 호출이 수백 번 드는 실행이니 반복하지 않는다) |
| SLO weekly / Eval review monthly | 매주 / 매달 | 보고서 성격. 급하지 않다 |
| Alert on failure | 위 작업이 실패할 때 | GitHub 이슈를 연다 |

장애 메일(Cloud Monitoring)은 rndigkwk@gmail.com으로 온다. 알림 정책은 `scripts/gcp/alert_policies.json`, 설치는 Cloud Shell에서 `setup_alerts.sh`(`ALERT_EMAIL=rndigkwk@gmail.com`)다.

## 7. 로컬에서 직접 확인하기

PowerShell, 저장소 폴더에서:

```powershell
uv run python -m unittest discover -s tests
```

- 이 PC에는 진료비 표와 보고서 PDF가 없어 테스트 10개 정도가 실패하는 것이 정상이다(CI에서는 통과).
- 평가 스크립트(`scripts/evaluate_*.py`)는 실제 모델을 불러 비용이 든다. 실행 전에 예상 호출 수와 그날의 누계가 표시되고, 한 번에 200번이 넘으면 확인을 묻는다(`scripts/cost_guard.py`).

## 하지 않을 것

- 키와 토큰을 채팅·이슈·로그에 붙여 넣지 않는다. 새 키는 콘솔에서 만들어 Secret Manager나 GitHub Secrets에만 넣는다.
- `fault` 연습(chat, supabase)은 운영 장애 중에 돌리지 않는다.
- 롤백 중에 강제 푸시(force-push)로 main 기록을 지우지 않는다. 되돌릴 때는 4절의 트래픽 이동이나 되돌리는 PR을 쓴다.
