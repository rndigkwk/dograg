# Terraform (드리프트 확인)

`infra/terraform/`은 이미 있는 GCP 자원을 코드로 적은 것이다(2026-11-11). **적용(`apply`)하지 않는다.** 운영 변경은 지금처럼 배포 워크플로와 소유자의 `gcloud` 명령으로 하고, Terraform은 "코드에 적힌 것과 실제가 같은가"만 본다.

## 무엇이 들어 있나

| 파일 | 자원 |
| --- | --- |
| `cloud_run.tf` | API 서비스 `ragdog-api`(CPU·메모리, 동시 요청 80, 최대 인스턴스 2, 시작 확인), 공개 호출 권한, 배포 계정의 관리 권한 |
| `registry.tf` | Artifact Registry `ragdog`(비공개, 최신 3개 이미지 유지), 배포 계정의 쓰기 권한 |
| `identity.tf` | Workload Identity 풀·공급자(main 브랜치만), 서비스 계정 3개(배포, 실행, SLO 읽기)와 권한 |
| `secrets.tf` | 비밀 6개의 **이름과 읽기 권한만**. 값은 Terraform과 상태 파일을 거치지 않는다 |
| `imports.tf` | 위 27개를 가져오는 `import` 블록 |

**배포가 바꾸는 값은 비교하지 않는다:** 이미지, 환경 변수(`LANGFUSE_RELEASE`가 커밋), 리비전 이름, 트래픽과 `candidate` 태그. 나머지(자원 크기, 확장 한도, 실행 계정, 권한)는 손으로 바꾸면 잡힌다.

## 상태 없이 확인하는 방법

상태 파일(state)을 두지 않는다. 확인할 때마다 빈 상태에서 `import` 블록으로 27개를 다시 읽고 plan을 만든다. 결과는 늘 "27 to import"이고, **"0 to add, 0 to change, 0 to destroy"여야 통과**다. 상태를 둘 버킷, 잠금, 상태에 남는 값의 관리가 필요 없다.

2026-11-11 첫 확인: `Plan: 27 to import, 0 to add, 0 to change, 0 to destroy.`

## CI (`terraform-plan.yml`)

- **PR:** `fmt -check`와 `validate`만 한다. Workload Identity가 main 브랜치만 받기 때문이다.
- **main 병합, 매주 월요일, 수동 실행:** 읽기 전용 계정 `terraform-plan`으로 로그인해 plan을 만든다. 0이 아니면 실패하고, `Alert on failure`가 이슈를 연다.
- **필요한 계정(소유자가 한 번 만든다):** `terraform-plan`에 `roles/viewer`와 `roles/iam.securityReviewer`(권한 정책 읽기)만 준다. 쓰기 권한은 없다. 이 계정 자체는 아직 코드에 넣지 않았다. 만든 뒤 `identity.tf`와 `imports.tf`에 더한다.

## 로컬에서

```powershell
cd infra/terraform
$env:GOOGLE_OAUTH_ACCESS_TOKEN = gcloud auth print-access-token
terraform init
terraform plan
```
