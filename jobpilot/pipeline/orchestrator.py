"""多 Agent 编排：LangGraph 串起四个 Agent。

    START → Agent1(解析简历) → Agent2(搜岗位) → Agent3(抓JD+匹配) → Agent4(决策+话术) → END

每个 Agent 是一个节点、只返回自己负责的字段；trace 逐节点累积，便于回放每一步。
"""

from __future__ import annotations

import time
from typing import Dict, List, TypedDict

from langgraph.graph import END, START, StateGraph

from agents import decide_agent, match_agent, resume_agent, search_agent
from .resume_io import read_text


class PipelineState(TypedDict, total=False):
    resume_text: str
    profile: Dict
    keywords: List[str]
    jobs: List[Dict]
    decisions: List[Dict]
    threshold: int
    limit: int
    tool: object
    trace: List[str]
    errors: List[str]
    elapsed_ms: int


def _safe(name, fn):
    """单个 Agent 抛异常时不让整条流水线崩掉，把错误记进 state 继续走。"""

    def inner(state: PipelineState) -> Dict:
        try:
            return fn(state)
        except Exception as exc:  # noqa: BLE001
            trace = list(state.get("trace") or [])
            trace.append(f"{name} 失败：{type(exc).__name__}: {exc}")
            errors = list(state.get("errors") or [])
            errors.append(f"{name}: {exc}")
            return {"errors": errors, "trace": trace}

    return inner


def _agent1(state: PipelineState) -> Dict:
    return resume_agent.run(state)


def _agent2(state: PipelineState) -> Dict:
    return search_agent.run(state, tool=state.get("tool"))


def _agent3(state: PipelineState) -> Dict:
    return match_agent.run(state)


def _agent4(state: PipelineState) -> Dict:
    return decide_agent.run(state)


def _after_resume(state: PipelineState) -> str:
    """简历解析失败（或没有画像）就直接结束，不进入搜索。"""
    if state.get("errors") or not state.get("profile"):
        return "stop"
    return "continue"


def build():
    g = StateGraph(PipelineState)
    g.add_node("agent1_resume", _safe("Agent1", _agent1))
    g.add_node("agent2_search", _safe("Agent2", _agent2))
    g.add_node("agent3_match", _safe("Agent3", _agent3))
    g.add_node("agent4_decide", _safe("Agent4", _agent4))

    g.add_edge(START, "agent1_resume")
    # 简历解析失败就没必要往下跑：拿假画像去投递比报错严重
    g.add_conditional_edges(
        "agent1_resume",
        _after_resume,
        {"continue": "agent2_search", "stop": END},
    )
    g.add_edge("agent2_search", "agent3_match")
    g.add_edge("agent3_match", "agent4_decide")
    g.add_edge("agent4_decide", END)
    return g.compile()


GRAPH = build()


def run_pipeline(resume_text: str, threshold: int = 60, limit: int = 8, tool=None) -> Dict:
    started = time.time()
    final = GRAPH.invoke({
        "resume_text": resume_text,
        "threshold": threshold,
        "limit": limit,
        "tool": tool,
        "trace": [],
    })
    # 归一化：提前结束的路径也要有无害的空列表，避免调用方 KeyError
    final.setdefault("jobs", [])
    final.setdefault("decisions", [])
    final.setdefault("trace", [])
    final["elapsed_ms"] = int((time.time() - started) * 1000)
    return final
