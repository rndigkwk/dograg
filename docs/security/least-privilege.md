# 최소 권한 점검 (2026-10-23, 교안 day64 실행 레일)

교안의 실행 레일은 "에이전트와 계정마다 그 일에 필요한 권한만"을 요구한다. 라그도그에서 무엇이 무엇을 할 수 있는지 실제 설정에서 확인했다.
DB 권한은 Supabase 카탈로그를 읽기 전용으로 조회했다. GCP는 설정 스크립트(`scripts/gcp/setup_cloud_run.sh`), GitHub는 워크플로 파일을 봤다.

## 1. 점검 결과

| 주체 | 할 수 있는 것 | 판단 |
| --- | --- | --- |
| DB `ragdog_app` (API) | 검색 표 2개 읽기. 자료 공백·피드백·평가 기록은 넣기만. 질문 횟수 읽기·넣기·지우기. `visit_prep` 스키마 읽기·쓰기. 보관 기간 정리 함수 실행 | 맞음. 슈퍼유저·역할 생성·DB 생성·RLS 우회 모두 없음. 사용자 표(대화·노트·프로필) 권한 없음 |
| DB `ragdog_app` (CI) | 위와 같은 계정을 주간 회귀·8시간 점검이 같이 쓴다 | **빈틈 1.** CI는 평가 기록 넣기만 필요하다. CI 비밀이 새면 질문 횟수 표와 방문 준비 실행까지 고칠 수 있다 |
| 방문 준비 연구 에이전트 | 역할마다 검색 도구 하나(상담 검색, 병원 찾기, 보고서 통계, 지역 진료비). 모두 읽기. 도구 호출·모델 호출 횟수 제한 | 맞음 |
| 방문 준비 작성 에이전트 | 이번 실행 폴더의 `visit_report.md` 하나 쓰기(경로는 에이전트가 못 정함), 검수·추가 조사 넘기기. 검색 도구 없음 | 맞음 |
| 채팅 그래프의 바깥 호출 | OpenAI, Decisions API(고정 주소), Supabase. 모델이 고르는 주소는 없음 | 맞음 |
| Cloud Run 실행 계정 `ragdog-runtime` | 지정한 비밀 몇 개 읽기만. 프로젝트 역할 없음 | 맞음 |
| 배포 계정 `github-deployer` | **프로젝트 전체 `run.admin`**, 이미지 저장소 쓰기, 실행 계정으로 배포 | **빈틈 2.** 프로젝트의 다른 Cloud Run 서비스도 만들고 지울 수 있다 |
| GitHub → GCP 신원 연결 | 이 저장소의 **모든 브랜치** 워크플로가 배포 계정이 될 수 있다 | **빈틈 2.** 배포와 롤백은 main에서만 돈다 |
| GitHub 워크플로 토큰 | 대부분 `contents: read`. 이슈를 여는 두 워크플로만 `issues: write`, 배포 둘만 `id-token: write` | 맞음 |

## 2. 고칠 것 (사용자가 실행)

비밀번호와 IAM을 바꾸는 일이라 사용자가 Supabase SQL 편집기와 Cloud Shell에서 직접 한다.

### 빈틈 1: CI 전용 DB 계정

1. Supabase SQL 편집기에서 실행한다. 비밀번호는 직접 만든다.
   ```sql
   create role ragdog_ci login password '직접 만든 비밀번호';
   grant usage on schema public to ragdog_ci;
   grant select on ragdog_health, ragdog_report to ragdog_ci;
   create policy ragdog_ci_read on ragdog_health for select to ragdog_ci using (true);
   create policy ragdog_ci_read on ragdog_report for select to ragdog_ci using (true);
   grant insert on ragdog_eval_history to ragdog_ci;
   create policy ragdog_ci_insert on ragdog_eval_history for insert to ragdog_ci with check (true);
   grant usage on sequence ragdog_eval_history_id_seq to ragdog_ci;
   ```
2. GitHub 저장소 비밀 `SUPABASE_DB_URL`의 사용자 이름과 비밀번호를 `ragdog_ci`로 바꾼다. Cloud Run의 Secret Manager 값은 그대로 `ragdog_app`이다.
3. 다음 주간 회귀가 평가 기록을 넣는 것을 확인한 뒤, API 계정의 평가 기록 권한을 거둔다.
   ```sql
   revoke insert on ragdog_eval_history from ragdog_app;
   drop policy ragdog_app_insert on ragdog_eval_history;
   ```

8시간 점검(`keep-alive.yml`)도 평가 기록만 넣으므로 같은 비밀로 된다.

### 빈틈 2: 배포 계정은 이 서비스만, main에서만

Cloud Shell에서 실행한다.
```bash
PROJECT=ragdog-511311; REGION=asia-northeast3; DEPLOYER=github-deployer@$PROJECT.iam.gserviceaccount.com
# 1) main 브랜치의 워크플로만 배포 계정이 된다
gcloud iam workload-identity-pools providers update-oidc dograg --location=global --workload-identity-pool=github \
  --attribute-condition="assertion.repository == 'rndigkwk/dograg' && assertion.ref == 'refs/heads/main'"
# 2) run.admin을 ragdog-api 서비스에만 주고, 프로젝트에는 읽기만 남긴다
gcloud run services add-iam-policy-binding ragdog-api --region=$REGION --member="serviceAccount:$DEPLOYER" --role=roles/run.admin
gcloud projects add-iam-policy-binding $PROJECT --member="serviceAccount:$DEPLOYER" --role=roles/run.viewer --condition=None
gcloud projects remove-iam-policy-binding $PROJECT --member="serviceAccount:$DEPLOYER" --role=roles/run.admin --condition=None
```
그다음 Actions에서 `Deploy to Cloud Run`을 수동으로 한 번 돌려 카나리와 승격이 통과하는지 본다. 실패하면 프로젝트 `run.admin`을 다시 붙이고(`add-iam-policy-binding … --role=roles/run.admin`), 로그의 권한 이름을 확인한다.

## 3. 바꾸지 않은 것

- **`ragdog_app`의 `visit_prep` 읽기·쓰기·지우기:** LangGraph 체크포인트 저장소가 실행마다 쓰고 지운다.
- **보관 기간 정리 함수(security definer):** API가 지우기 권한 없이 3년 지난 행만 지우게 하려고 일부러 둔 것이다(`scripts/sql/retention.sql`).
- **DB 연결 수 제한:** API 최대 인스턴스가 2개라 연결이 몇 개뿐이다. 문제가 생기면 그때 `connection limit`을 건다.

## 4. 진행 상황 (2026-10-24)

| 빈틈 | 단계 | 상태 | 확인 |
| --- | --- | --- | --- |
| 1 | `ragdog_ci` 계정과 권한 | 완료 | 카탈로그: 로그인 가능, RLS 우회 없음. 읽기 2개, 평가 기록 넣기, 시퀀스 사용만 있음 |
| 1 | GitHub 비밀을 `ragdog_ci`로 | 완료 | 8시간 점검을 수동 실행: 건강 문서 19,206건 읽기, 평가 기록 넣기(id 603) 성공 |
| 1 | `ragdog_app`의 평가 기록 넣기 거두기 | 10-26 주간 회귀 뒤 | 회귀가 `ragdog_ci`로 기록을 넣은 것을 보고 실행 |
| 2 | 신원 연결은 main 브랜치만, `run.admin`은 `ragdog-api`만 + 프로젝트 `run.viewer` | 완료 | 병합 배포 2번(#313, #314)이 좁힌 권한으로 카나리·트래픽 전환까지 통과(리비전 `ragdog-api-00185`) |

- **주의(빈틈 1에서 겪음):** GitHub 비밀에는 **pooler 주소**(`aws-0-ap-northeast-2.pooler.supabase.com`, 사용자 이름 `ragdog_ci.<프로젝트 id>`)를 넣는다. 대시보드의 직접 연결 주소(`db.<프로젝트 id>.supabase.co`)는 IPv6만 있어 GitHub 실행기에서 `Network is unreachable`로 실패했다.
- **브랜치에서 배포·롤백은 이제 안 된다.** 시험은 PR의 검사로 하고, 배포는 main 병합이나 main에서 수동 실행으로만 한다.
