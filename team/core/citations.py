"""Core layer: turn the report's evidence ids into short numbers for people.

The writer cites the researchers' ids ([qa-17403], [hospital-3230000010199...]) and the
reviewer checks against them, so the saved report keeps them. For reading and downloading,
each id becomes a circled number in order of first use, and a source list goes at the end.
"""

from __future__ import annotations

import re

CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"
# Citations the writer may use besides the researchers' ids.
FIXED_SOURCES = {
    "상담 내용": "보호자 상담 내용",
    "보호자 상담 내용": "보호자 상담 내용",
    "응급 판정": "응급 징후 자동 판정 (상담 내용의 표현 기준)",
    "반려견 정보": "보호자가 입력한 반려견 정보",
    "지역": "보호자가 입력한 지역",
    "수집 실패": "조사 중 오류로 이번에 모으지 못한 자료",
}
# One or more [id] in a row; a markdown link ([text](url)) is not a citation.
CITATION_RUN = re.compile(r"(?:[ \t]*\[[^\[\]\n]{1,160}\](?!\())+")
CITATION = re.compile(r"\[([^\[\]\n]{1,160})\]")
REPORT_ID = re.compile(r"report-(.+)-p(\d+|\?)$")
FACT_CHARS = 70


def marker(number: int) -> str:
    return CIRCLED[number - 1] if number <= len(CIRCLED) else f"({number})"


def _short(text: str) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= FACT_CHARS else text[:FACT_CHARS].rstrip() + "…"


def source_labels(findings: dict) -> dict[str, str]:
    """A readable line for every id the researchers returned, and for each task summary."""
    labels = dict(FIXED_SOURCES)
    for task_id, finding in findings.items():
        labels[task_id] = f"조사 {task_id} 요약: {_short(finding.get('summary', ''))}"
        for point in finding.get("key_points", []):
            evidence_id = point["evidence_id"]
            if evidence_id in labels:
                continue
            fact = _short(point.get("fact", ""))
            if report := REPORT_ID.match(evidence_id):
                title, page = report.groups()
                labels[evidence_id] = f"보고서 「{title.replace('+', ' ')}」 {page}쪽: {fact}"
            elif evidence_id.startswith("qa-"):
                labels[evidence_id] = f"비슷한 건강 상담 사례 (AI Hub {evidence_id}): {fact}"
            elif evidence_id.startswith("hospital-"):
                labels[evidence_id] = f"동물병원 공공데이터: {fact}"
            elif evidence_id.startswith("guide-"):
                labels[evidence_id] = f"기본 안내 (조사로 통계를 찾지 못했을 때 쓰는 고정 문구): {fact}"
            else:
                labels[evidence_id] = fact or evidence_id
    return labels


def number_citations(report: str, findings: dict) -> tuple[str, list[tuple[str, str, str]]]:
    """The report with known ids as ①②…, and [(marker, id, label)] in order of first use.
    A bracket that is not a known id stays as written."""
    labels = source_labels(findings)
    numbers: dict[str, int] = {}

    def replace(run: re.Match) -> str:
        ids = [token.strip() for token in CITATION.findall(run.group())]
        if not all(token in labels for token in ids):
            return run.group()
        markers = []
        for token in ids:
            numbers.setdefault(token, len(numbers) + 1)
            mark = marker(numbers[token])
            if mark not in markers:
                markers.append(mark)
        return " " + "".join(markers)

    numbered = CITATION_RUN.sub(replace, report)
    sources = [(marker(number), token, labels[token]) for token, number in numbers.items()]
    return numbered, sources


def readable_report(report: str, findings: dict) -> str:
    """The numbered report with its source list at the end (what the app shows and downloads)."""
    numbered, sources = number_citations(report, findings)
    if not sources:
        return numbered
    lines = "  \n".join(f"{mark} {label}" for mark, _, label in sources)
    return f"{numbered.rstrip()}\n\n---\n\n#### 근거\n\n{lines}\n"
