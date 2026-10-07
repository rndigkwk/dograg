"""Graph layer: planner, researcher, supervisor, writer, reviewer and publisher nodes."""

from __future__ import annotations

import json
from typing import Literal

from langgraph.runtime import Runtime
from langgraph.types import Command

from src.faithfulness import build_judge, build_verifier, recheck_unsupported
from team.agents.workers import create_researcher
from team.core import config
from team.core.prompts import (
    PLANNER_INPUT,
    PLANNER_PROMPT,
    RESEARCHER_INPUT,
    REWORK_INPUT,
    REWORK_PROMPT,
    WRITER_INPUT,
)
from team.core.schemas import ReworkStep, VisitPlan

WRITE_WITH_WHAT_EXISTS = ("추가 조사는 이미 한 번 했습니다. 지금 조사 결과만으로 보고서를 쓰고, "
                          "자료에 없는 내용은 '자료로 확인할 수 없음'이라고 적은 뒤 request_review를 부르세요.")
from team.graph.state import Context, ResearchInput, State


def dump_json(data) -> str:
    return json.dumps(data, ensure_ascii=False, indent=1)


def evidence_text(state: State) -> str:
    """What the report may say: the consultation itself and every researcher's facts with ids."""
    lines = [f"[상담 내용] {state['consultation']}"]
    if state["profile"]:
        lines.append(f"[반려견 정보] {state['profile']}")
    if state["urgent"]:
        # Decided by code (src/health_safety.py) from the consultation: the report's warning cites it.
        lines.append(f"[응급 판정] 상담 내용에서 응급 징후가 감지됨: {state['urgent']}")
    if state["region"]:
        lines.append(f"[지역] 보호자가 입력한 지역: {state['region']}")
    for task_id, finding in sorted(state["findings"].items()):
        lines.append(f"[{task_id} 요약] {finding['summary']}")
        lines += [f"[{point['evidence_id']}] {point['fact']}" for point in finding["key_points"]]
    return "\n".join(lines)


# --- planner ----------------------------------------------------------------------
def planner(state: State) -> dict:
    """Split the consultation into research tasks; the number depends on the consultation."""
    max_tasks = config.MAX_EXTRA_TASKS if state["findings"] else config.MAX_TASKS
    done = [f"{task['kind']}: {task['query']}" for task in state["plan"]] or "없음"
    message = PLANNER_INPUT.format(
        consultation=state["consultation"], region=state["region"] or "없음", profile=state["profile"] or "없음",
        urgent=state["urgent"] or "없음", done=done, instruction=state["instruction"] or "없음",
    )
    plan = config.llm().with_structured_output(VisitPlan).invoke(
        [("system", PLANNER_PROMPT.format(max_tasks=max_tasks)), ("user", message)]
    )
    tasks = [task.model_dump() for task in plan.tasks[:max_tasks]]
    if any(task["kind"] == "place" for task in state["plan"]):
        # The hospital tool takes only the region, so a second place task returns the same list.
        tasks = [task for task in tasks if task["kind"] != "place"]
    if not state["plan"] and state["region"] and not any(task["kind"] == "place" for task in tasks):
        # The guardian gave an area: the report always lists hospitals there.
        tasks = tasks[: max_tasks - 1] + [{"kind": "place", "query": state["region"], "angle": "가까운 동물병원"}]
    for offset, task in enumerate(tasks, start=1):
        task["task_id"] = f"t{len(state['plan']) + offset}"  # numbered in code so ids never repeat
        task["extra"] = bool(state["plan"])  # added after a rejection or a research request
    print("planner:", len(tasks), "개 작업", [f"{task['task_id']} {task['kind']}" for task in tasks])
    return {"plan": state["plan"] + tasks, "review": None, "instruction": ""}


# --- researcher (one per task, in parallel through Send) -----------------------------------
def researcher(state: ResearchInput) -> dict:
    task = state["task"]
    print("researcher:", task["task_id"], task["kind"], task["query"])
    agent = create_researcher(task["kind"])
    message = RESEARCHER_INPUT.format(query=task["query"], angle=task["angle"], consultation=state["consultation"])
    if task["kind"] == "place":
        # Decided here, not by the model: an urgent consultation lists 24h/emergency names first.
        if state["urgent"]:
            message += "\n[응급] 예. find_hospitals를 emergency=True로 한 번 부르세요."
        else:
            message += "\n[응급] 아니요. find_hospitals를 emergency=False로 한 번 부르세요."
    result = agent.invoke({"messages": message})
    finding = result.get("structured_response")
    if finding is None:  # call limit reached before an answer
        finding_dict = {"summary": "조사 상한에 닿아 결과를 정리하지 못했습니다.", "key_points": []}
    else:
        finding_dict = finding.model_dump()
    finding_dict["kind"] = task["kind"]
    return {"findings": {task["task_id"]: finding_dict}}


# --- supervisor -------------------------------------------------------------------------
def supervisor(state: State) -> Command[Literal["planner", "writer", "publisher"]]:
    review = state["review"]
    if state["round"] >= config.MAX_ROUNDS:
        # No more rework: a rejected report goes out marked for a person to check.
        if review is not None and not review.get("passed"):
            print("supervisor:", "반복 상한 도달 -> publisher (사람 확인 필요)")
            return Command(goto="publisher")
        return Command(goto="writer")
    if review is not None and review.get("by") == "writer" and any(task.get("extra") for task in state["plan"]):
        # The team already researched once more for the writer; another round finds the same data.
        print("supervisor:", f"반려 {state['round'] + 1}회 -> writer (추가 조사는 한 번만)")
        return Command(goto="writer", update={"round": state["round"] + 1, "instruction": WRITE_WITH_WHAT_EXISTS})
    if review is not None and not review.get("passed"):
        message = REWORK_INPUT.format(feedback=state["feedback"], findings=dump_json(state["findings"]))
        step = config.llm().with_structured_output(ReworkStep).invoke(
            [("system", REWORK_PROMPT), ("user", message)]
        )
        print("supervisor:", f"반려 {state['round'] + 1}회 ->", step.next)
        return Command(goto=step.next, update={"round": state["round"] + 1, "instruction": step.instruction})
    print("supervisor:", "첫 작성 -> writer" if state["round"] == 0 else "추가 조사 반영 -> writer")
    return Command(goto="writer")


# --- writer: hands off through its own tools ------------------------------------------------
def writer(state: State, runtime: Runtime[Context]) -> Command[Literal["reviewer"]]:
    run_dir = runtime.context["run_dir"]
    report_path = run_dir / config.REPORT_FILE
    print("writer:", "다시 쓰기" if state["feedback"] else "첫 초안")
    message = WRITER_INPUT.format(
        consultation=state["consultation"], profile=state["profile"] or "없음", urgent=state["urgent"] or "없음",
        findings=dump_json(state["findings"]), feedback=state["feedback"] or "없음",
        instruction=state["instruction"] or "없음",
        previous=report_path.read_text(encoding="utf-8") if report_path.exists() else "없음",
    )
    # When the writer calls request_review or request_research, control leaves here for the
    # outer graph and the line below does not run.
    runtime.context["writer"].invoke({"messages": message})
    print("writer:", "핸드오프 없이 끝나 reviewer로 넘김")
    return Command(goto="reviewer", update={"draft": config.REPORT_FILE})


# --- reviewer ---------------------------------------------------------------------------
def reviewer(state: State, runtime: Runtime[Context]) -> Command[Literal["publisher", "supervisor"]]:
    """Pass only when no claim in the report is missing from the consultation and the findings."""
    path = runtime.context["run_dir"] / config.REPORT_FILE
    if not path.exists():
        review = {"passed": False, "unsupported": [], "reason": "보고서 파일이 없습니다."}
        return Command(goto="supervisor", update={"review": review, "feedback": "write_report로 보고서를 먼저 저장하세요."})
    report = path.read_text(encoding="utf-8")
    context = evidence_text(state)
    judgment = build_judge(config.review_llm()).invoke(
        {"question": state["consultation"], "context": context, "answer": report}
    )
    verifier = build_verifier(config.review_llm())
    recheck_unsupported(judgment, context, lambda claim: verifier.invoke({"context": context, "claim": claim}))
    unsupported = [claim.text for claim in judgment.claims if claim.verdict == "unsupported"]
    supported = sum(claim.verdict == "supported" for claim in judgment.claims)
    review = {"passed": not unsupported, "supported": supported, "unsupported": unsupported}
    print("reviewer:", "통과" if review["passed"] else f"반려 (근거 없는 주장 {len(unsupported)}개)")
    if review["passed"]:
        return Command(goto="publisher", update={"review": review})
    feedback = "조사 결과와 상담 내용에 근거가 없는 문장입니다. 지우거나 근거가 있는 내용으로 고치세요:\n" + "\n".join(
        f"- {claim}" for claim in unsupported
    )
    return Command(goto="supervisor", update={"review": review, "feedback": feedback})


# --- publisher --------------------------------------------------------------------------
def publisher(state: State, runtime: Runtime[Context]) -> dict:
    run_dir = runtime.context["run_dir"]
    passed = bool(state["review"] and state["review"].get("passed"))
    status = config.PASSED if passed else config.HUMAN_CHECK
    path = run_dir / config.REPORT_FILE
    if not passed and path.exists():
        # Keep the draft, but nobody may mistake it for a checked report.
        path.write_text(f"> ⚠️ {status}. 아래 내용 중 근거가 확인되지 않은 문장이 있습니다.\n\n" + path.read_text(encoding="utf-8"),
                        encoding="utf-8")
    elif not passed:
        # The writer never wrote one (it kept asking for research): still leave a report for the person.
        path.write_text(
            f"# 방문 준비 보고서\n\n> ⚠️ {status}. 근거를 찾지 못해 보고서를 만들지 못했습니다.\n\n"
            f"## 보호자 상담 내용\n{state['consultation']}\n\n## 마지막 요청\n{state['feedback'] or '없음'}\n\n"
            "이 보고서는 진단이 아니며 수의사의 진료를 대신하지 않습니다.\n",
            encoding="utf-8",
        )
    record = {
        "status": status,
        "round": state["round"],
        "review": state["review"],
        "feedback": state["feedback"],
        "urgent": state["urgent"],
        "plan": state["plan"],
        "findings": state["findings"],
    }
    (run_dir / config.RESULT_FILE).write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    print("publisher:", status)
    return {}
