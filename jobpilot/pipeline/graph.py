"""决策图：LangGraph 编排「解析 JD → 打分 → 路由 → 生成话术 / 拒绝」。

这是 jobgraph 那套图在生产链路里的复用版：节点更少，但接的是真实数据流
（扩展上报的 JD → 图 → 入库 → 看板）。
"""

from __future__ import annotations

import re
from typing import Dict, List, TypedDict

from langgraph.graph import END, START, StateGraph

CORE = ["Python", "Agent|智能体", "LLM|大模型", "LangGraph|LangChain", "MCP", "RAG|知识库"]
BONUS = ["React", "MySQL|SQL", "FastAPI", "Redis", "Qdrant|向量数据库", "WebSocket", "Docker"]
EXCLUDE = ["java", "销售", "标注", "训练师", "客服"]

CORE_W = 3
BONUS_W = 1


class State(TypedDict, total=False):
    job_id: str
    title: str
    company: str
    salary: str
    jd: str
    threshold: int
    score: int
    matched: List[str]
    missing: List[str]
    banned: str
    decision: str
    reason: str
    greeting: str


def _alts(group: str) -> List[str]:
    return [p.strip() for p in group.split("|") if p.strip()]


def parse(state: State) -> Dict:
    jd = (state.get("jd") or "").strip()
    return {"jd": re.sub(r"\n{2,}", "\n", jd)}


def score(state: State) -> Dict:
    jd = state.get("jd") or ""
    title = state.get("title") or ""

    for word in EXCLUDE:
        if word.lower() in title.lower():
            return {"score": 0, "banned": word, "matched": [], "missing": []}

    items = [(g, CORE_W) for g in CORE] + [(g, BONUS_W) for g in BONUS]
    total = sum(w for _, w in items) or 1
    got, matched, missing = 0, [], []
    for group, weight in items:
        if any(re.search(re.escape(a), jd, re.IGNORECASE) for a in _alts(group)):
            got += weight
            matched.append(_alts(group)[0])
        else:
            missing.append(_alts(group)[0])
    return {"score": round(got / total * 100), "matched": matched, "missing": missing}


def route(state: State) -> str:
    return "apply" if int(state.get("score") or 0) >= int(state.get("threshold") or 60) else "skip"


def draft(state: State) -> Dict:
    skills = "、".join((state.get("matched") or [])[:3]) or "Python 与智能体开发"
    greeting = (
        f"您好，我是27届本科应届生，方向是 AI Agent 应用开发。"
        f"看到「{state.get('title', '这个岗位')}」，要求里的{skills}我都有实际项目经验，"
        f"方便聊聊吗？"
    )
    return {"decision": "apply", "reason": f"匹配 {state.get('score')} 分", "greeting": greeting}


def reject(state: State) -> Dict:
    if state.get("banned"):
        reason = f"标题命中排除词「{state.get('banned')}」"
    else:
        reason = f"匹配 {state.get('score')} 分，低于阈值 {state.get('threshold')}"
    return {"decision": "skip", "reason": reason, "greeting": ""}


def build():
    g = StateGraph(State)
    g.add_node("parse", parse)
    g.add_node("score", score)
    g.add_node("draft", draft)
    g.add_node("reject", reject)
    g.add_edge(START, "parse")
    g.add_edge("parse", "score")
    g.add_conditional_edges("score", route, {"apply": "draft", "skip": "reject"})
    g.add_edge("draft", END)
    g.add_edge("reject", END)
    return g.compile()


GRAPH = build()


def evaluate(job: Dict, threshold: int = 60) -> Dict:
    init = {
        "job_id": job.get("job_id", ""),
        "title": job.get("title", ""),
        "company": job.get("company", ""),
        "salary": job.get("salary", ""),
        "jd": job.get("jd", ""),
        "threshold": threshold,
    }
    return GRAPH.invoke(init)
