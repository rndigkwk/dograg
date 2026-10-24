"""Answer rail ANS-03 (rails/rails.yml): a fixed line when a health answer finds no home care.

The consultations are vets' answers about symptoms; what to do at home is rarely in them. From
2026-10-15 to 10-24, 6 of the 17 gaps the health answers stated (ragdog_data_gaps) were "the
material has no home care for this" (vomiting, diarrhoea, itching, paw licking), and no public
guide with a clear licence was found to fill them (2026-10-24). So the answer keeps saying the
material lacks it, and this line says what is safe without the material: watch, record, no human
medicine, and the vet when it goes on. Not for an urgent sign: that warning already says go now.
"""

from __future__ import annotations

import re

from src.data_gaps import gap_sentences

# A gap sentence about care at home: "집에서 할 수 있는 관리 방법은 없습니다", "집 관리법",
# "대처법은 검색된 자료에 없습니다", "집에서 할 처치 방법은".
_HOME = re.compile(r"집|가정|관리\s?(?:법|방법)|처치|대처|해\s?줄 수 있는")

NOTE = ("🏠 집에서는: 상담 자료에 집에서 하는 관리법이 없어 방법을 지어내지 않았어요. 증상이 언제, 얼마나 자주 "
        "나타나는지 적고 사진이나 영상을 남겨 두면 진료 때 도움이 돼요. 사람 약을 먹이거나 바르지 마세요. 증상이 "
        "계속되거나 심해지면, 기운이나 식욕이 떨어지면 동물병원 진료를 받으세요. 먹으면 안 되는 것을 먹었다면 "
        "기다리지 말고 바로 병원에 연락하세요.")


def home_care_note(answer: str) -> str:
    """NOTE when the answer says the material has no home care, else ""."""
    return NOTE if any(_HOME.search(sentence) for sentence in gap_sentences(answer)) else ""
