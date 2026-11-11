# Kubernetes (kind)

운영은 Cloud Run이다([ADR-0013](adr/0013-cloud-run-not-kubernetes.md)). 이 문서는 같은 이미지를 Kubernetes에서 띄우는 방법과 CI의 확인을 적는다.

## 무엇이 있나

| 파일 | 내용 |
| --- | --- |
| `deploy/k8s/api.yaml` | API Deployment(시작 2분까지 기다리는 startupProbe, readiness·liveness `/health`), Service(80 → 8080), HPA(CPU 70%, 1~3개), ConfigMap(`RAGDOG_METRICS=1`, 추적 끔) |
| `deploy/k8s/prometheus.yaml` | Prometheus v3.5.0 하나. 네임스페이스 안 파드만 읽는 Role로 파드를 찾고, `prometheus.io/scrape` 주석이 있는 파드의 `/metrics`를 15초마다 긁는다 |
| `api/metrics.py` | `ragdog_requests_total{route,method,status}`, `ragdog_request_seconds{route}`. `RAGDOG_METRICS=1`일 때만 붙는다 |
| `.github/workflows/k8s-kind.yml` | kind 클러스터에서 위를 배포하고 확인한다 |

## 로컬에서

kind와 kubectl이 있어야 한다. 이미지는 비공개 데이터를 담으므로 로컬 클러스터에만 올린다.

```powershell
docker build --secret id=hf_token,env=HF_TOKEN -t ragdog-api:kind .
kind create cluster --name ragdog
kind load docker-image ragdog-api:kind --name ragdog
kubectl apply -k deploy/k8s
kubectl -n ragdog port-forward service/ragdog-api 8080:80
```

질문까지 해 보려면 모델·Supabase 키를 Secret `ragdog-api`로 넣는다(`kubectl -n ragdog create secret generic ragdog-api --from-env-file=.env`). 그러면 Langfuse 추적은 ConfigMap이 꺼 둔 채로 남는다. 다 쓰면 `kind delete cluster --name ragdog`.

## CI가 확인하는 것

1. 이미지 빌드, kind에 올리기, metrics-server 설치(kind의 kubelet 인증서 때문에 `--kubelet-insecure-tls`).
2. `kubectl apply -k`, 두 Deployment의 rollout 완료.
3. Service로 `/health` 6번, `/metrics`에 `route="/health",status="200"` 카운터.
4. Prometheus 쿼리 `up{job="ragdog-api"}`가 1이고 `ragdog_requests_total{route="/health"}`가 잡힐 때까지 최대 3분.
5. HPA 상태는 출력만 한다.

모델 호출, GCP 접속, 이미지 push는 없다.
