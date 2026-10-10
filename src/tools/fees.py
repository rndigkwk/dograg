"""Regional animal-clinic fee statistics (data/vet_fees/vet_fees.csv, scripts/collect_vet_fees.py).

The government's 2025 fee survey (animalclinicfee.or.kr, Veterinarians Act disclosure): for 19 fee
items, split by weight or species where the survey splits them, the mean, median, minimum and
maximum per si/gun/gu, si/do and nationally. Answers come straight from the table, without a model
call, and always say that these are regional statistics, not any hospital's price.

A question is a fee question when it asks about cost (진료비, 비용, 얼마 ...) and names a surveyed
item (초진, 종합백신, 엑스레이, MRI ...) or clinic fees in general (진료비, 병원비). Insurance,
spending and report-style questions (보험, 양육비, 통계 ...) stay with the report path.
"""

from __future__ import annotations

import csv
import re
from functools import lru_cache

from src import resources
from src.tools import places

FEE_CSV = resources.DATA_DIR / "vet_fees" / "vet_fees.csv"
SOURCE = "농림축산식품부 동물병원 진료비 현황 조사(2025, animalclinicfee.or.kr)"
NOTICE = (f"출처: {SOURCE}. 지역별 조사 통계이며 개별 병원의 가격이 아닙니다. "
          "병원마다 다르니 방문 전에 전화로 확인하세요.")

COST_WORDS = ("진료비", "병원비", "비용", "가격", "요금", "값", "금액", "드나요", "들어요", "몇만원", "비싸",
              "검사비", "촬영비", "접종비", "입원비", "진찰료", "상담료", "예방비", "구충비", "판독료")
# "얼마" asks for money when the question ends there or goes on to a price ("얼마예요", "얼마나 나와요",
# "얼마 정도 해요"); "얼마나 자주", "얼마나 걸려요", "얼마 동안", "얼마 뒤에" ask how often or how long
# (holdout, 2026-10-10: 4 of 20 non-fee questions took the fee path this way). Matched on the
# question without spaces.
MONEY_EOLMA = re.compile(r"얼마(?:나|정도|쯤)?(?:$|[?!.,~()]|예|에|야|요|인|일|이|를|정도|쯤|해|하|나와|나오|나올|들|드|돼|되|받|씩|면|라|든|짜리|줘|주|만원)")
GENERAL_FEE_WORDS = ("진료비", "병원비")
# "진료비" alone is a topic, not a price question ("진료비 카드 할부 되나요?", "진료비가 많이 나왔는데
# 어디에 신고해요?"): without a surveyed item, the question must also ask for an amount.
AMOUNT_ASKS = ("평균", "가격", "시세", "수준", "대충", "보통", "몇만원")
# Spending, insurance and survey questions belong to the report path (KB report etc.).
NOT_FEE_WORDS = ("보험", "보고서", "통계", "양육비", "지출", "연간", "월평균", "한 달", "평균적으로 얼마나 써",
                 "수술")  # surgery is not in the survey ("슬개골 수술비", "수술 비용이 부담돼 깁스를")
# A fee lookup is a short question; a long consultation that mentions an x-ray and its cost is a
# health question (seen in the CRAG set).
MAX_FEE_QUESTION_CHARS = 120
VACCINE_ITEMS = ("광견병백신 접종비", "켄넬코프백신 접종비", "코로나바이러스백신 접종비", "인플루엔자백신 접종비")
# Surveyed items: words a guardian uses -> the item title on the site.
ITEM_WORDS = (
    ("초진", "초진 진찰료"), ("재진", "재진 진찰료"), ("상담료", "진찰에 대한 상담료"), ("상담비", "진찰에 대한 상담료"),
    ("진찰료", "초진 진찰료"), ("입원", "입원비"),
    ("종합백신", "종합백신 접종비"), ("종합 백신", "종합백신 접종비"), ("종합접종", "종합백신 접종비"),
    ("예방접종", "종합백신 접종비"), ("백신", "종합백신 접종비"),
    ("광견병", "광견병백신 접종비"), ("켄넬코프", "켄넬코프백신 접종비"), ("코로나", "코로나바이러스백신 접종비"),
    ("인플루엔자", "인플루엔자백신 접종비"), ("독감", "인플루엔자백신 접종비"),
    ("혈액화학", "혈액화학 검사비와 판독료"), ("생화학", "혈액화학 검사비와 판독료"),
    ("전해질", "전해질 검사비와 판독료"), ("전혈구", "전혈구 검사비와 판독료"), ("cbc", "전혈구 검사비와 판독료"),
    ("피검사", "전혈구 검사비와 판독료"), ("혈액검사", "전혈구 검사비와 판독료"), ("혈액 검사", "전혈구 검사비와 판독료"),
    ("엑스레이", "엑스선 촬영비와 판독료"), ("엑스선", "엑스선 촬영비와 판독료"), ("x-ray", "엑스선 촬영비와 판독료"),
    ("x레이", "엑스선 촬영비와 판독료"), ("방사선", "엑스선 촬영비와 판독료"),
    ("초음파", "초음파 검사비와 판독료"), ("mri", "자기공명영상검사(MRI)비와 판독료"),
    ("ct", "컴퓨터단층촬영검사(CT)비와 판독료"), ("씨티", "컴퓨터단층촬영검사(CT)비와 판독료"),
    ("심장사상충", "심장사상충 예방비"), ("외부기생충", "외부기생충 예방비"), ("진드기", "외부기생충 예방비"),
    ("벼룩", "외부기생충 예방비"), ("구충", "광범위 구충비"),
)
# Shown for "강남구 진료비 얼마야?": the items most visits involve.
GENERAL_ITEMS = ("초진 진찰료", "재진 진찰료", "종합백신 접종비", "전혈구 검사비와 판독료", "엑스선 촬영비와 판독료")
WEIGHTS = (5, 10, 20)


@lru_cache(maxsize=2)
def load_fee_rows(path: str = str(FEE_CSV)) -> tuple[dict, ...]:
    try:
        with open(path, encoding="utf-8-sig", newline="") as file:
            return tuple(csv.DictReader(file))
    except FileNotFoundError:
        return ()


def _compact(text: str) -> str:
    return "".join(text.lower().split())


def requested_items(question: str) -> list[str]:
    compact = _compact(question)
    found = []
    for word, item in ITEM_WORDS:
        # "ct" and "cbc" only as words: "엑스레이 ct" yes, "ctrl" or "elect" no.
        hit = re.search(rf"(?<![a-z]){word}(?![a-z])", compact) if word.isascii() else word in compact
        if hit and item not in found:
            found.append(item)
    # "독감 예방접종", "광견병 백신": the named vaccine, not the combination vaccine "예방접종" and
    # "백신" stand for by default.
    if "종합백신 접종비" in found and any(item in found for item in VACCINE_ITEMS) and "종합" not in compact:
        found.remove("종합백신 접종비")
    return found


def is_fee_question(question: str) -> bool:
    compact = _compact(question)
    if len(question) > MAX_FEE_QUESTION_CHARS or not load_fee_rows():
        return False
    if any(_compact(word) in compact for word in NOT_FEE_WORDS):
        return False
    money_eolma = bool(MONEY_EOLMA.search(compact))
    if not money_eolma and not any(word in compact for word in COST_WORDS):
        return False
    if requested_items(question):
        return True
    return (any(word in compact for word in GENERAL_FEE_WORDS)
            and (money_eolma or any(word in compact for word in AMOUNT_ASKS)))


def requested_weight(question: str, profile=None) -> int | None:
    """5, 10 or 20 kg (the survey's reference weights) from "7kg" in the question or the saved profile."""
    match = re.search(r"(\d+(?:\.\d+)?)\s*(?:kg|킬로|키로)", question.lower())
    weight = float(match.group(1)) if match else getattr(profile, "weight_kg", None)
    if not weight:
        return None
    return 5 if weight <= 7.5 else 10 if weight <= 15 else 20


def requested_species(question: str, profile=None) -> str:
    text = question + " " + str(getattr(profile, "species", "") or "")
    return "고양이" if any(word in text for word in ("고양이", "냥이", "냥")) else "개"


def resolve_regions(question: str) -> list[tuple[str, str]]:
    """(si/do, si/gun/gu or "") pairs the question names, as written in the fee table."""
    rows = load_fee_rows()
    sigungu_of = {}
    for row in rows:
        if row["level"] == "sigungu":
            sigungu_of.setdefault(row["sigungu"], set()).add(row["sido"])
    sidos = {row["sido"] for row in rows if row["level"] == "sido"}
    keywords = places.extract_search_parameters(question)
    # The region extractor keeps only the most specific words ("부산 중구" -> 중구), so read the
    # si/do from the question itself; it decides which 중구 is meant.
    compact = _compact(question)
    named_sidos = sorted({full for alias, full in places.SIDO_ALIASES.items() if alias in compact}
                         | {sido for sido in sidos if sido in compact})
    found = []
    for keyword in keywords:
        if keyword in sidos:
            continue
        candidates = sigungu_of.get(keyword, set())
        if not candidates:
            # A gu inside a city ("분당구") is published at city level ("성남시"): look the city up.
            city = _city_of(keyword)
            candidates = {sido for sido in sigungu_of.get(city or "", set())}
            keyword = city or keyword
        for sido in sorted(candidates):
            if not named_sidos or sido in named_sidos:
                found.append((sido, keyword))
    if not found:
        found = [(sido, "") for sido in named_sidos]
    return list(dict.fromkeys(found))[:3]


def _city_of(gu: str) -> str | None:
    rows = places.execute_place_sql(
        "SELECT road_address FROM place WHERE road_address LIKE ? LIMIT 1", [f"% {gu} %"])
    if rows:
        words = rows[0]["road_address"].split()
        index = words.index(gu) if gu in words else -1
        if index > 0 and words[index - 1].endswith("시"):
            return words[index - 1]
    return None


def _pick_details(rows: list[dict], weight: int | None, species: str) -> list[dict]:
    """The rows for one item: the asked weight/species if the survey splits by it, else all of them."""
    def matches(row):
        detail = row["detail"]
        if "고양이" in detail or detail == "개" or detail.startswith("개 "):
            if species not in detail:
                return False
        if weight and "kg" in detail:
            return f"{weight}kg" in detail
        return True
    chosen = [row for row in rows if matches(row)]
    return chosen or rows


def _won(value: str) -> str:
    return f"{int(value):,}원"


def _line(row: dict) -> str:
    return (f"중간 {_won(row['median'])} · 평균 {_won(row['mean'])} "
            f"(최저 {_won(row['min'])} ~ 최고 {_won(row['max'])})")


def _label(item: str, detail: str) -> str:
    return f"{item} ({detail})" if detail and detail != "기타 상담 행위" else item


def fee_lookup(question: str, profile=None) -> list[dict]:
    """Rows to show: for each item and detail, the most specific region with data and the nation."""
    rows = load_fee_rows()
    items = requested_items(question) or list(GENERAL_ITEMS)
    weight, species = requested_weight(question, profile), requested_species(question, profile)
    if not requested_items(question):
        weight = weight or 5  # the general overview shows one reference weight per item
    regions = resolve_regions(question)
    results = []
    for item in items:
        item_rows = [row for row in rows if row["item"] == item]
        national = {(row["detail"]): row for row in item_rows if row["level"] == "national"}
        variants = list({row["detail"]: row for row in item_rows}.values())  # one row per weight/species
        for detail_row in _pick_details(variants, weight, species):
            detail = detail_row["detail"]
            entry = {"item": item, "detail": detail, "national": national.get(detail), "regions": []}
            for sido, sigungu in regions:
                local = next((row for row in item_rows if row["detail"] == detail and row["sido"] == sido
                              and row["sigungu"] == sigungu and row["level"] == ("sigungu" if sigungu else "sido")), None)
                fallback = None if local or not sigungu else next(
                    (row for row in item_rows if row["detail"] == detail and row["sido"] == sido and row["level"] == "sido"), None)
                entry["regions"].append({"name": " ".join(filter(None, (sido, sigungu))), "row": local,
                                         "sido_row": fallback, "sido": sido})
            results.append(entry)
    return results


def fee_answer(question: str, profile=None) -> str:
    results = fee_lookup(question, profile)
    if not results:
        return "진료비 조사 자료에서 이 항목을 찾지 못했습니다. " + NOTICE
    lines = []
    general = not requested_items(question)
    if general:
        lines.append("자주 쓰는 진료 항목의 지역별 진료비입니다(개, 체중 5kg 기준).")
    for entry in results:
        lines.append(f"\n**{_label(entry['item'], entry['detail'])}**")
        for region in entry["regions"]:
            if region["row"]:
                lines.append(f"- {region['name']}: {_line(region['row'])}")
            elif region["sido_row"]:
                lines.append(f"- {region['name']}: 조사 값 없음 → {region['sido']} 전체 {_line(region['sido_row'])}")
            else:
                lines.append(f"- {region['name']}: 조사 값 없음")
        if entry["national"]:
            lines.append(f"- 전국: {_line(entry['national'])}")
    regions = resolve_regions(question)
    if not regions:
        lines.append("\n지역(예: 강남구, 수원)을 함께 말씀하시면 그 지역의 값을 보여 드립니다.")
    elif len({sigungu for _, sigungu in regions}) < len(regions):
        lines.append("\n같은 이름의 지역이 여러 시·도에 있습니다. 시·도를 함께 말씀하시면(예: 부산 중구) "
                     "그 지역만 보여 드립니다.")
    lines.append(f"\n{NOTICE}")
    return "\n".join(lines).strip()
