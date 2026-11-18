"""MCP Server：把 JobPilot 的能力暴露成 MCP 工具，供 Claude / Cursor 等 Agent 直接调用。

启动（stdio）：
    python -m pipeline.mcp_server

在 Claude Desktop / Cursor 的 mcp 配置里加：
    {"command": "python", "args": ["-m", "pipeline.mcp_server"], "cwd": "<jobpilot 目录>"}
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from mcp.server.mcpserver import MCPServer

from . import graph
from .api import cache, db
from .config import CONFIG

mcp = MCPServer(name="jobpilot")


@mcp.tool()
def evaluate_jd(jd_text: str, title: str = "", company: str = "") -> str:
    """评估一份 JD 与本人技能的匹配度，返回分数、决策与推荐话术。"""
    final = graph.evaluate({"jd": jd_text, "title": title, "company": company},
                           CONFIG.score_threshold)
    return json.dumps({
        "score": final.get("score"),
        "decision": final.get("decision"),
        "reason": final.get("reason"),
        "matched": final.get("matched"),
        "missing": final.get("missing"),
        "greeting": final.get("greeting"),
    }, ensure_ascii=False, indent=2)


@mcp.tool()
def list_jobs(limit: int = 20, decision: str = "") -> str:
    """列出已入库的岗位；decision 可传 apply / skip 过滤。"""
    items: List[Dict[str, Any]] = db.list_jobs(limit=limit, decision=decision or None)
    slim = [{k: row.get(k) for k in ("job_id", "title", "company", "salary", "score", "decision")}
            for row in items]
    return json.dumps(slim, ensure_ascii=False, indent=2)


@mcp.tool()
def get_stats() -> str:
    """返回投递统计：总数、通过数、跳过数、平均分、今日已投。"""
    return json.dumps({**db.stats(), "today_count": cache.daily_count()}, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    mcp.run()
