"""技能词典：按类别分组，英文词用词边界匹配，避免 Go 命中 Google 这类误判。

用法：
    extract_skills(text) -> ["Python", "LangGraph", ...]
"""

from __future__ import annotations

import re
from typing import Dict, List

# 分组只为可读性，最终输出是扁平列表
SKILL_GROUPS: Dict[str, List[str]] = {
    "语言": [
        "Python", "Java", "Go|Golang", "C++", "C#", "JavaScript|JS", "TypeScript|TS",
        "Rust", "PHP", "Ruby", "Kotlin", "Scala", "SQL", "Shell|Bash",
    ],
    "后端": [
        "FastAPI", "Flask", "Django", "Spring Boot|SpringBoot", "Node.js|NodeJS",
        "Express", "gRPC", "RESTful|REST API", "GraphQL",
    ],
    "前端": [
        "React", "Vue", "Next.js|NextJS", "HTML", "CSS", "Tailwind", "Webpack",
    ],
    "AI/Agent": [
        "Agent|智能体", "LLM|大模型|大语言模型", "RAG|检索增强", "LangChain", "LangGraph",
        "MCP|Model Context Protocol", "Prompt|提示词", "Function Calling|工具调用",
        "Fine-tune|微调", "Embedding|向量化", "多模态", "向量数据库", "OpenAI", "DeepSeek",
    ],
    "数据/存储": [
        "MySQL", "PostgreSQL", "MongoDB", "Redis", "Elasticsearch|ES", "Qdrant",
        "Milvus", "Pinecone", "Kafka", "RabbitMQ", "Pandas", "NumPy", "ClickHouse",
    ],
    "云原生/运维": [
        "Docker", "Kubernetes|K8s", "Linux", "Nginx", "CI/CD", "GitHub Actions",
        "Jenkins", "AWS", "阿里云", "腾讯云", "Prometheus",
    ],
    "工具/协作": [
        "Git", "Cursor", "Claude", "Copilot", "Figma", "Jira", "Postman", "WebSocket",
    ],
}

_TOTAL = sum(len(v) for v in SKILL_GROUPS.values())


def _alts(group: str) -> List[str]:
    return [p.strip() for p in group.split("|") if p.strip()]


def _hit(text_lower: str, term: str) -> bool:
    """英文词加边界；中文词直接子串匹配。

    为什么必须加边界：`Go` 用子串会命中 `Google`、`Django`，`React` 会命中 `Reactive`。
    """
    t = term.lower()
    escaped = re.escape(t)
    if re.fullmatch(r"[\x00-\x7f]+", t):
        pattern = rf"(?<![a-z0-9]){escaped}(?![a-z0-9])"
        return re.search(pattern, text_lower) is not None
    return t in text_lower


def extract_skills(text: str) -> List[str]:
    """返回命中的技能（用每组第一个词作为标准名）。"""
    lower = (text or "").lower()
    found: List[str] = []
    for group in SKILL_GROUPS.values():
        for item in group:
            if any(_hit(lower, alt) for alt in _alts(item)):
                name = _alts(item)[0]
                if name not in found:
                    found.append(name)
    return found


def stats() -> Dict[str, int]:
    return {"groups": len(SKILL_GROUPS), "terms": _TOTAL}
