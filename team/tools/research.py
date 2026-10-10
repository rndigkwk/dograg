"""Tools layer: one research tool per researcher, built on the RagDog chatbot's modules.

Each researcher gets only its own tool (RESEARCH_TOOLS), so the place researcher cannot
read consultation Q&A and the writer cannot search at all. Tool results are JSON with an
evidence_id per item; researchers cite those ids and the reviewer checks against them.
"""

from __future__ import annotations

import json
import threading

from langchain.tools import tool

from src.crag import HEALTH_CANDIDATE_K, evidence_id, grade_documents
from src.tools import fees, health, places, report
from src.tools.review import review_evidence

# Researchers run in parallel threads (Send). The search indexes (Kiwi tokenizer, BM25,
# Chroma) are shared process-wide and were not written for concurrent use, so searches
# take turns; the slow part, the model calls, still runs in parallel.
_SEARCH_LOCK = threading.Lock()
EXCERPT_CHARS = 500


def _dumps(items: list[dict]) -> str:
    return json.dumps(items, ensure_ascii=False)


def _health_text(doc) -> str:
    return f"질문: {doc.page_content}\n답변: {doc.metadata.get('qa.output', '')}"


@tool
def search_health_qa(query: str) -> str:
    """반려견 건강 상담 Q&A(AI Hub, 19,206건)에서 증상 하나에 맞는 상담 사례를 찾습니다.
    하이브리드 검색 뒤 근거 평가로 질문에 쓸모 있는 사례만 남깁니다."""
    filters = health.infer_rag_filters(query)
    with _SEARCH_LOCK:
        docs = health.retrieve_health(query, k=HEALTH_CANDIDATE_K, filters=filters)
    kept, decision, _ = grade_documents(
        lambda question, context: review_evidence("health", question, context), query, docs, _health_text,
    )
    if not kept:
        return _dumps([{"note": "이 증상에 쓸 수 있는 상담 근거를 찾지 못했습니다.", "decision": decision}])
    return _dumps([{
        "evidence_id": f"qa-{evidence_id(doc)}",
        "life_stage": doc.metadata.get("meta.lifeCycle"),
        "department": doc.metadata.get("meta.department"),
        "question": doc.page_content[:EXCERPT_CHARS],
        "answer": str(doc.metadata.get("qa.output", ""))[:EXCERPT_CHARS],
    } for doc in kept])


@tool
def find_hospitals(region: str, emergency: bool = False) -> str:
    """지역(시·군·구 이름)의 동물병원을 공공데이터 시설 DB에서 최대 5곳 찾습니다.
    emergency=True면 이름에 24시·응급·야간이 들어간 병원을 먼저 보여 줍니다(영업시간 정보는 없음)."""
    keywords = places.extract_search_parameters(region) or [region.strip()]
    conditions = " OR ".join("road_address LIKE ? OR lot_address LIKE ?" for _ in keywords)
    parameters = ["hospital"] + [f"%{keyword}%" for keyword in keywords for _ in range(2)]
    rows = places.execute_place_sql(
        f"SELECT {places.RESULT_COLUMNS} FROM place WHERE kind = ? AND ({conditions}) ORDER BY id", parameters,
    )
    night = [row for row in rows if any(word in row["name"] for word in places.EMERGENCY_NAME_WORDS)]
    ordered = (night + [row for row in rows if row not in night]) if emergency else rows
    if not ordered:
        return _dumps([{"note": f"'{region}'에서 동물병원을 찾지 못했습니다."}])
    return _dumps([{
        "evidence_id": row["id"],
        "name": row["name"],
        "address": row.get("road_address") or row.get("lot_address"),
        "phone": row.get("phone"),
        "name_says_24h_or_emergency": row in night,
    } for row in ordered[:5]])


@tool
def search_report_stats(query: str) -> str:
    """반려동물 보고서 5종(KB 2025 반려동물 보고서, 의료보험서비스 시장 진단 등)에서
    진료비·보험·지출 통계를 찾습니다."""
    with _SEARCH_LOCK:
        docs = report.search_reports(query)
    if not docs:
        return _dumps([{"note": "관련 보고서 근거를 찾지 못했습니다."}])
    return _dumps([{
        "evidence_id": f"report-{doc.metadata.get('title', '보고서')}-p{doc.metadata.get('page', '?')}",
        "title": doc.metadata.get("title"),
        "page": doc.metadata.get("page"),
        "excerpt": doc.page_content[:EXCERPT_CHARS],
    } for doc in docs[:4]])


@tool
def regional_fee_stats(region: str, item: str, weight_kg: float = 0) -> str:
    """동물병원 진료비 현황(농림축산식품부 2025 조사)에서 지역·진료 항목의 진료비 통계(중간·평균·최저·최고)를 찾습니다.
    region: 시·군·구나 시·도 이름(모르면 빈 문자열이면 전국만). item: 초진 진찰료, 재진, 입원비, 종합백신, 광견병,
    혈액검사, 엑스레이, 초음파, CT, MRI, 심장사상충, 외부기생충, 구충 중 하나. weight_kg: 반려견 체중(모르면 0).
    지역별 조사 통계이며 개별 병원의 가격이 아닙니다."""
    question = f"{region} {item} 진료비" + (f" {weight_kg}kg" if weight_kg else "")
    if not fees.requested_items(question):
        return _dumps([{"note": f"'{item}'은 진료비 조사 항목이 아닙니다(중성화·수술비 등은 조사하지 않음)."}])
    found = []
    for entry in fees.fee_lookup(question):
        label = fees._label(entry["item"], entry["detail"])
        places_and_rows = [(r["name"], r["row"] or r["sido_row"]) for r in entry["regions"]]
        places_and_rows.append(("전국", entry["national"]))
        for name, row in places_and_rows:
            if not row:
                continue
            found.append({
                "evidence_id": "fee-" + "-".join(f"{name} {label}".split()),
                "region": name if row["level"] != "sido" or name == row["sido"] else f"{row['sido']} 전체({name} 값 없음)",
                "item": label,
                "median": int(row["median"]), "mean": int(row["mean"]), "min": int(row["min"]), "max": int(row["max"]),
                "note": "2025 조사의 지역 통계, 개별 병원 가격 아님",
            })
    return _dumps(found or [{"note": "진료비 조사 자료에서 찾지 못했습니다."}])


RESEARCH_TOOLS = {
    "health": [search_health_qa],
    "place": [find_hospitals],
    "cost": [regional_fee_stats, search_report_stats],
}
