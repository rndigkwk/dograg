"""Time each feature of the deployed API: chat routes 3 runs each, one visit-prep report, lookups 10 each.

    python -I scripts/measure_latency_by_feature.py OUT.json   (every run to OUT.json, a summary printed)

Model calls (2026-10-25): about 50 for the chat runs and 10-20 for the report, so run it rarely
(docs/wiki/deployment-resources.md, 기능별 응답 시간). Each chat feature asks as its own browser id:
a person may ask 10 questions an hour (src/rate_limit.py); the network limit still applies. The
report counts against that id's 2 a day. Avoid the 8-hour check's minutes (keep-alive.yml, :17).
"""
import json
import statistics
import sys
import time
import urllib.parse
import urllib.request
import uuid

API = "https://ragdog-api-892238791473.asia-northeast3.run.app"
ORIGIN = "https://ragdog-rndigkwks-projects.vercel.app"
CHAT = [  # (feature, question, route)
    ("건강 상담", "강아지가 이틀째 설사를 해요", None),
    ("응급 질문", "강아지 잇몸이 파랗고 숨을 헐떡여요", None),
    ("보고서 질문", "반려견 양육 가구의 월평균 양육비는 얼마인가요?", "report"),
    ("시설 찾기", "강남구 24시 동물병원 알려줘", None),
    ("진료비", "서울 강아지 엑스레이 비용 얼마예요?", None),
]
LOOKUPS = [
    ("시설 목록", "/places/search?" + urllib.parse.urlencode({"kind": "hospital", "province": "서울특별시", "city": "강남구"})),
    ("가까운 시설", "/places/nearby?kind=hospital&lat=37.4979&lon=127.0276"),
    ("응급 병원", "/places/emergency?lat=37.4979&lon=127.0276"),
    ("지역 진료비", "/fees/region?" + urllib.parse.urlencode({"province": "서울특별시", "city": "강남구"})),
    ("데이터 통계", "/stats/overview"),
]
RUNS, LOOKUP_RUNS = 3, 10
sys.stdout.reconfigure(encoding="utf-8")


def stream(path: str, body: dict, client: str) -> dict:
    """POST an SSE request; seconds to the first event, evidence, first token, end; the result."""
    request = urllib.request.Request(API + path, data=json.dumps(body).encode(), headers={
        "Content-Type": "application/json", "Origin": ORIGIN, "X-RagDog-Client": client})
    start, out, event = time.monotonic(), {"events": {}}, None
    with urllib.request.urlopen(request, timeout=300) as response:
        for raw in response:
            line = raw.decode("utf-8").rstrip("\n")
            if line.startswith("event:"):
                event = line[6:].strip()
                now = round(time.monotonic() - start, 2)
                out["events"][event] = out["events"].get(event, 0) + 1
                out.setdefault("first_event", now)
                out.setdefault(f"first_{event}", now)
            elif line.startswith("data:") and event in ("result", "paused", "error", "limited"):
                out["data"] = json.loads(line[5:])
    out["total"] = round(time.monotonic() - start, 2)
    return out


def get(path: str) -> float:
    start = time.monotonic()
    with urllib.request.urlopen(urllib.request.Request(API + path, headers={"Origin": ORIGIN}), timeout=60) as response:
        response.read()
    return round(time.monotonic() - start, 3)


def summary(values: list[float]) -> str:
    return f"중앙값 {statistics.median(values):.1f}초 ({min(values):.1f}~{max(values):.1f})" if values else "-"


records = {"started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
records["cold_health_seconds"] = get("/health")  # the first request may start an instance
print(f"첫 /health: {records['cold_health_seconds']}초")
time.sleep(2)
records["warm_health_seconds"] = get("/health")
print(f"두 번째 /health: {records['warm_health_seconds']}초")

for feature, question, route in CHAT:
    client = uuid.uuid4().hex  # one browser per feature: 10 questions an hour each
    body = {"question": question, **({"route": route} if route else {})}
    runs = []
    for i in range(RUNS):
        run = stream("/chat", body, client)
        data = run.pop("data", {})
        run["route"], run["abstained"], run["guards"] = data.get("route"), data.get("abstained"), data.get("guards")
        runs.append(run)
        print(f"{feature} {i + 1}: 전체 {run['total']}초, 첫 단계 {run.get('first_step')}, 근거 {run.get('first_evidence')}, "
              f"첫 글자 {run.get('first_token')}, 경로 {run['route']}, 이벤트 {run['events']}")
        sys.stdout.flush()
        time.sleep(2)
    records[feature] = runs

client = uuid.uuid4().hex
report = {"consultation": "7살 말티즈가 이틀째 기침을 하고 밤에 더 심해요. 밥은 잘 먹어요.", "region": "서울특별시 강남구", "profile": "말티즈, 7살, 수컷"}
first = stream("/visit-prep", report, client)
data = first.pop("data", {})
visit = {"first": first, "paused": "thread_id" in data and "questions" in data}
print(f"방문 준비 1단계: {first['total']}초, 이벤트 {first['events']}, 질문 {data.get('questions')}")
if visit["paused"]:
    second = stream(f"/visit-prep/{data['thread_id']}/answer", {"answer": "기침은 마른기침이고 열은 재 보지 않았어요."}, client)
    result = second.pop("data", {})
    visit["second"] = second
    visit["result"] = {key: result.get(key) for key in ("passed", "status", "round", "seconds")}
    print(f"방문 준비 2단계(답한 뒤): {second['total']}초, 결과 {visit['result']}")
else:
    visit["result"] = {key: data.get(key) for key in ("passed", "status", "round", "seconds")}
records["방문 준비 보고서"] = visit

for name, path in LOOKUPS:
    records[name] = [get(path) for _ in range(LOOKUP_RUNS)]
    print(f"{name}: 첫 요청 {records[name][0]}초, 중앙값 {statistics.median(records[name]):.3f}초")

print("\n== 요약 (채팅 3회 중앙값, 최소~최대)")
for feature, _, _ in CHAT:
    runs = records[feature]
    tokens = [r["first_token"] for r in runs if "first_token" in r]
    evidence = [r["first_evidence"] for r in runs if "first_evidence" in r]
    print(f"{feature:6} 전체 {summary([r['total'] for r in runs])} | 첫 글자 {summary(tokens)} | 근거 {summary(evidence)}")
with open(sys.argv[1], "w", encoding="utf-8") as out:
    json.dump(records, out, ensure_ascii=False, indent=1)
