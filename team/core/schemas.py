"""Core layer: structured outputs of the planner, researchers and supervisor."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

TaskKind = Literal["health", "place", "cost"]


class VisitTask(BaseModel):
    """One research task. The planner's code adds task_id."""
    kind: TaskKind = Field(description="health: 증상·질병 상담 근거, place: 근처 동물병원, cost: 진료비·보험 통계")
    query: str = Field(description="그 담당의 도구에 그대로 넣을 짧은 검색어 또는 지역")
    angle: str = Field(description="이 조사로 알아낼 것 한 문장")


class VisitPlan(BaseModel):
    tasks: list[VisitTask] = Field(description="조사 작업 목록")


class KeyPoint(BaseModel):
    fact: str = Field(description="보고서에 쓸 사실 한 문장. 도구 결과에 있는 내용만")
    evidence_id: str = Field(description="이 사실이 나온 도구 결과의 evidence_id")


class Finding(BaseModel):
    """One researcher's result."""
    summary: str = Field(description="조사 결과 요약 2~3문장. 근거가 없으면 없다고 쓴다")
    key_points: list[KeyPoint] = Field(description="사실과 그 근거 id")


class Clarification(BaseModel):
    """Before planning: what to ask the guardian, if anything."""
    questions: list[str] = Field(
        description="보고서에 꼭 필요한데 상담 내용에 없는 정보를 묻는 짧은 질문. 상담 내용이 충분하면 빈 목록"
    )


class ReworkStep(BaseModel):
    """After a rejection: who works next and what to do."""
    next: Literal["writer", "planner"] = Field(
        description="writer: 지금 조사 결과로 고쳐 쓸 수 있음. planner: 조사 결과에 없는 정보를 더 조사해야 함"
    )
    instruction: str = Field(description="그 담당이 바로 할 일. 검수 피드백을 구체적인 작업으로 바꾼 지시문")
