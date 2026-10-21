"""Synthetic training questions for a small route/urgency classifier (real model calls).

    uv run python scripts/make_classifier_data.py          # about 40 calls

The classifier (scripts/train_small_classifier.py) would stand in for the two OpenAI Decisions calls
the app makes when its rules decide nothing: the route of a question (src/tools/router.py) and
whether it is an emergency (src/tools/urgency.py). The labelled questions we have are the evaluation
sets (136 routing, 120 emergency), so training needs other questions: a chat model writes them, from
the label descriptions only. No evaluation question is shown to it.

Each call asks for BATCH questions of one label in one style; the styles vary the length and tone
(a short line, a long story, 반말, typos) and the hard cases mix signals ("토하는데 근처 병원 찾아줘"
is a place search, "구토하는데 병원 가야 하나요" is a health question). Duplicates are dropped.
Output: data/classifier/train.jsonl ({"text", "task", "label"}), synthetic text only.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from pydantic import BaseModel, Field

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))
sys.path.insert(0, str(PROJECT_DIR / "scripts"))

OUT = PROJECT_DIR / "data" / "classifier" / "train.jsonl"
BATCH = 25
LABELS = {
    "route": {
        "rag": "반려견의 건강·증상·질병·약·관리·행동·영양에 대한 질문, 반려동물을 잃은 뒤의 절차나 슬픔(보호자가 자기 개의 상태를 설명하거나 일반 건강 정보를 묻는다). 고양이·토끼 등 다른 동물의 건강 질문도 여기다.",
        "sql": "반려동물 시설을 찾는 요청: 동물병원·동물약국·반려동물 동반 시설(카페, 펜션 등)·애견미용·위탁(호텔)·장묘 시설의 위치·주소·전화·영업·개수를 지역이나 '근처'로 묻는다.",
        "analysis": "반려동물 관련 조사·보고서·통계를 묻는 질문: 양육 가구 수, 월평균 양육비, 입양 경로, 보험 가입률, 시장 규모, 진료비 지출 같은 통계나 보고서 내용.",
        "none": "반려동물 상담이 아닌 말: 인사·감사·잡담, 날씨·뉴스·주식·코딩·번역·숙제 같은 범위 밖 요청, 챗봇에 대한 질문.",
    },
    "urgency": {
        "emergency_now": "몇 시간 안에 목숨이 위험할 수 있어 지금 바로 병원에 가야 하는 상황을 보호자가 적은 글: 숨쉬기 힘듦·잇몸이 파랗거나 하얌, 쓰러짐·의식 저하, 이어지는 경련, 독성 물질이나 사람 약을 먹음, 배가 부풀고 헛구역질만 함, 멈추지 않는 출혈, 교통사고·추락, 열사병, 소변을 전혀 못 봄, 난산, 눈 외상.",
        "see_vet_soon": "진료가 필요하지만 지금 당장 생명이 위험해 보이지는 않는 상황: 며칠째 구토·설사·식욕 부진, 혈변·혈뇨, 절뚝거림, 이물을 삼켰지만 잘 지냄, 치료 중인 병, 수술 뒤 회복 문제.",
        "not_urgent": "급하지 않은 글: 일상적인 증상, 이미 지나가 지금은 괜찮은 일, 증상이 없다고 밝힘, 일반 정보·예방·대처법 질문, 시설 찾기·보고서·인사처럼 증상 설명이 없는 질문.",
    },
}
STYLES = (
    "한 줄짜리 짧은 질문(10~25자)",
    "보호자가 사정을 길게 설명하는 글(2~4문장)",
    "반말이나 구어체, 맞춤법이 조금 틀린 글",
    "다른 갈래의 낱말이 섞여 헷갈리기 쉬운 글(예: 건강 이야기에 병원 낱말, 시설 요청에 증상 낱말, 통계 질문에 진료비 낱말)",
)
# Mixed-signal questions get more calls: they are where the rules give up and the classifier works.
REPEATS = {"route": {"rag": 1, "sql": 1, "analysis": 1, "none": 1}, "urgency": {"emergency_now": 1, "see_vet_soon": 1, "not_urgent": 1}}


class Questions(BaseModel):
    questions: list[str] = Field(description="서로 다른 질문들")


PROMPT = """반려견 상담 챗봇의 분류기를 학습시킬 한국어 질문을 만듭니다.
갈래: {label}
갈래 설명: {description}
문체: {style}

이 갈래에 속하는 서로 다른 질문 {n}개를 쓰세요. 상황·견종·나이·지역·낱말을 다양하게 바꾸고, 같은 문장 틀을 되풀이하지 마세요.
실제 보호자가 챗봇에 입력할 법한 글로만 쓰고, 번호나 설명은 붙이지 마세요."""


def jobs() -> list[tuple[str, str, str]]:
    return [(task, label, style) for task, labels in LABELS.items() for label in labels
            for style in STYLES for _ in range(REPEATS[task][label])]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--yes", action="store_true")
    args = parser.parse_args()
    from cost_guard import confirm

    todo = jobs()
    if not confirm("make_classifier_data", len(todo), f"{BATCH} questions per call", args.yes):
        return 1
    from src import resources

    model = resources.load_chat_model().with_structured_output(Questions)

    def write(job):
        task, label, style = job
        prompt = PROMPT.format(label=label, description=LABELS[task][label], style=style, n=BATCH)
        return job, model.invoke(prompt).questions

    rows, seen = [], set()
    with ThreadPoolExecutor(6) as pool:
        for (task, label, _), questions in pool.map(write, todo):
            for text in questions:
                key = (task, " ".join(text.split()))
                if key[1] and key not in seen:
                    seen.add(key)
                    rows.append({"text": key[1], "task": task, "label": label})
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    from collections import Counter

    print(len(rows), Counter((row["task"], row["label"]) for row in rows))
    return 0


if __name__ == "__main__":
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    raise SystemExit(main())
