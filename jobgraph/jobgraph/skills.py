"""技能画像：同义词组 + 权重。

一个技能用「竖线分隔的同义词组」表示，例：`LLM|大模型|大语言模型`。
JD 里出现任一写法即视为命中——中文 JD 很少写英文缩写，不做同义词组会系统性漏判。
"""

import json
from pathlib import Path
from typing import Dict, List

DEFAULT_PROFILE: Dict[str, List[str]] = {
    "core": [
        "Python",
        "Agent|智能体",
        "LLM|大模型|大语言模型",
        "LangGraph|LangChain",
        "MCP|Model Context Protocol",
        "RAG|检索增强|知识库",
    ],
    "bonus": [
        "React",
        "MySQL|SQL",
        "FastAPI",
        "Redis",
        "Qdrant|向量数据库",
        "WebSocket",
        "Docker",
    ],
    "exclude": ["java", "后端", "销售", "标注", "训练师", "客服"],
}

CORE_WEIGHT = 3
BONUS_WEIGHT = 1


def load_profile(path: str | None = None) -> Dict[str, List[str]]:
    """从 JSON 读画像；缺字段时用默认值补齐。"""
    if not path:
        return dict(DEFAULT_PROFILE)
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return {
        "core": raw.get("core", DEFAULT_PROFILE["core"]),
        "bonus": raw.get("bonus", DEFAULT_PROFILE["bonus"]),
        "exclude": raw.get("exclude", DEFAULT_PROFILE["exclude"]),
    }


def alternates(group: str) -> List[str]:
    """把 `LLM|大模型` 拆成 ['LLM', '大模型']。"""
    return [p.strip() for p in str(group).split("|") if p.strip()]


def display_name(group: str) -> str:
    return alternates(group)[0]


def weighted_items(profile: Dict[str, List[str]]):
    """展开成 (技能组, 权重) 列表。"""
    items = []
    for group in profile.get("core", []):
        items.append((group, CORE_WEIGHT))
    for group in profile.get("bonus", []):
        items.append((group, BONUS_WEIGHT))
    return items
