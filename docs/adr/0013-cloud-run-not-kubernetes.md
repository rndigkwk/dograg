# ADR-0013: 운영은 Cloud Run에 두고, Kubernetes는 kind 클러스터에서 이식만 확인한다

- **상태:** 채택 (2026-11-11)
- **관련:** [k8s.md](../k8s.md), [slo.md](../slo.md), 교안 Day 78·79

## 맥락

- **트래픽:** 하루 수십 개 요청이다. 대부분은 깨우기 점검과 배포 확인이다(주간 SLO 보고, 2026-11-11 최근 7일 요청 1,290개, 질문 60개).
- **비용:** Cloud Run은 질문이 없으면 인스턴스가 0개라 요금이 거의 없다. GKE는 노드(Standard)나 파드(Autopilot)가 늘 떠 있어야 해서, 이 앱이 쓰는 1 CPU·2 GiB만 해도 매달 고정 요금이 든다.
- **Prometheus:** 교안 Day 79는 앱의 `/metrics`를 Prometheus가 긁는다. Cloud Run에서는 인스턴스가 0개로 줄고 여러 개가 따로 떠서, 프로세스 안 카운터가 매번 0으로 돌아가고 인스턴스마다 나뉜다. 긁어 갈 서버도 늘 떠 있어야 한다. 같은 숫자(요청 수, 지연, 응답 코드)는 Cloud Monitoring에 이미 있다.
- **그래도 확인하고 싶은 것:** 같은 이미지가 클러스터에서도 뜨는지, 프로브·Service·HPA·Prometheus 수집이 맞게 돌아가는지.

## 결정

1. **운영은 Cloud Run 그대로 둔다.** 카나리, 롤백, Workload Identity 배포는 바꾸지 않는다.
2. **`deploy/k8s/`에 매니페스트를 둔다.** Deployment(시작·준비·생존 프로브는 `/health`), Service, HPA(CPU 70%, 1~3개), ConfigMap, 선택 Secret, 그리고 Prometheus(파드 발견, 네임스페이스 안 Role만)다.
3. **CI의 kind 클러스터에서 확인한다** (`.github/workflows/k8s-kind.yml`). 매니페스트·Dockerfile·`api/main.py`·`api/metrics.py`를 바꾼 PR과 수동 실행에서 돈다.
   - 이미지를 만들어 kind에 올리고(어디에도 push하지 않음), 배포가 준비될 때까지 기다린다.
   - Service로 `/health`를 부르고, `/metrics`에 그 요청이 세어졌는지, Prometheus가 파드를 `up=1`로 긁어 같은 수를 갖는지 확인한다.
   - GCP에 닿지 않고, 모델·Supabase 키를 넣지 않는다. 그래서 모델을 쓰는 질문은 이 확인에 없다.
4. **`/metrics`는 `RAGDOG_METRICS=1`일 때만 켠다.** Cloud Run에서는 꺼져 있다. 라벨은 경로 틀(`/places/{kind}`)이라 아무 주소나 두드려도 시계열이 늘지 않는다.

## 넣지 않은 것

- **GKE 운영 클러스터:** 위 비용. 트래픽이 늘어 인스턴스가 늘 떠 있어야 하면 다시 본다.
- **kube-prometheus-stack(Helm):** 연산자, Grafana, Alertmanager까지 깔려 이 확인에는 크다. Prometheus 하나와 설정 파일로 충분하다.
- **HPA 확장 확인:** kind에서 부하를 걸어 파드가 늘어나는지는 보지 않는다. 러너 CPU에 따라 흔들린다. HPA는 만들고 상태만 출력한다.

## 결과

- 이미지가 Cloud Run 밖에서도 같은 명령으로 뜬다는 것을 PR마다 확인한다.
- API 컨테이너는 아직 root로 돈다(Dockerfile에 `USER`가 없음, [lecture-review](../wiki/lecture-review.md) Day 78). 그래서 API 파드에는 `runAsNonRoot`를 걸지 않았다. Prometheus 파드는 root가 아닌 사용자로 돈다.

## 다시 검토할 조건

- 하루 질문이 늘어 Cloud Run 인스턴스가 늘 1개 이상 떠 있게 되면, GKE Autopilot과 요금을 비교한다.
