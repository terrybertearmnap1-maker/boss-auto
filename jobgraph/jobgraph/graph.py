"""把节点组装成 LangGraph 状态图。

    START → parse_jd → extract_skills → score ─┬─(score ≥ 阈值)→ draft_greeting → END
                                                └─(否则)────────→ reject        → END

条件边由 `nodes.route` 决定；compile 时挂 MemorySaver，支持按 thread_id 回放轨迹。
"""

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from .nodes import draft_greeting, extract_skills, parse_jd, reject, route, score
from .state import JobState


def build_graph(threshold: int = 60, with_memory: bool = True):
    """构建并编译图。

    Args:
        threshold: 默认阈值，实际以 state['threshold'] 为准。
        with_memory: 是否挂 MemorySaver（演示断点/回放时开启）。
    """
    graph = StateGraph(JobState)

    graph.add_node("parse_jd", parse_jd)
    graph.add_node("extract_skills", extract_skills)
    graph.add_node("score", score)
    graph.add_node("draft_greeting", draft_greeting)
    graph.add_node("reject", reject)

    graph.add_edge(START, "parse_jd")
    graph.add_edge("parse_jd", "extract_skills")
    graph.add_edge("extract_skills", "score")
    graph.add_conditional_edges(
        "score",
        route,
        {"apply": "draft_greeting", "skip": "reject"},
    )
    graph.add_edge("draft_greeting", END)
    graph.add_edge("reject", END)

    return graph.compile(checkpointer=MemorySaver() if with_memory else None)


def evaluate(job: dict, profile: dict, threshold: int = 60) -> dict:
    """评估单个岗位，返回最终状态（含命中技能、分数、决策、话术）。"""
    app = build_graph(threshold=threshold)
    config = {"configurable": {"thread_id": job.get("id") or job.get("title", "job")}}
    init: JobState = {
        "title": job.get("title", ""),
        "company": job.get("company", ""),
        "salary": job.get("salary", ""),
        "jd_text": job.get("jd_text", ""),
        "threshold": threshold,
        "profile": profile,   # 允许把画像放进 state，节点里无需全局变量
        "trace": [],
    }
    return app.invoke(init, config=config)
