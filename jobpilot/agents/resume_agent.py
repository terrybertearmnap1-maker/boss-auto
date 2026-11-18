"""Agent1：简历解析。

输入：简历纯文本（PDF 抽出来的）
输出：结构化画像 JSON —— 技能、方向、城市、薪资下限、学历、搜索关键词

设计取舍：有 LLM 时走 LLM 抽取，没有时用词典 + 正则兜底。
两条路返回同一份 schema，下游 Agent 不感知差异。
"""

from __future__ import annotations

import json
import os
import re
from typing import Dict, List

from pipeline.skill_dict import extract_skills

CITIES = ["广州", "深圳", "北京", "上海", "杭州", "成都", "武汉", "南京", "西安"]

# 简历里出现这些词 → 映射成搜索结果里的岗位关键词
# 注意：触发词必须足够"重"，用 SQL / React 这种会在 MySQL / 前端库里误触发
DIRECTION_RULES = [
    (["Agent", "智能体"], ["Agent", "智能体"]),
    (["大模型", "LLM", "RAG", "Prompt"], ["大模型", "AI应用"]),
    (["数据分析", "数据运营"], ["数据分析"]),
    (["前端开发", "前端工程师"], ["前端"]),
    (["Java", "Spring"], ["Java"]),
]


def _llm_extract(text: str) -> Dict | None:
    """有 OpenAI 兼容 key 时用模型抽取；失败返回 None 走规则。"""
    base, key = os.getenv("OPENAI_BASE_URL"), os.getenv("OPENAI_API_KEY")
    if not base or not key:
        return None
    try:
        import httpx

        prompt = (
            "你是简历解析器。只输出 JSON，字段：skills(list[str]), directions(list[str]), "
            "city(str), salary_min(int, 单位K), degree(str), keywords(list[str], 用于招聘网站搜索岗位)。\n"
            f"简历：\n{text[:6000]}"
        )
        resp = httpx.post(
            f"{base.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {key}"},
            json={"model": os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
                  "messages": [{"role": "user", "content": prompt}],
                  "temperature": 0},
            timeout=30,
        )
        content = resp.json()["choices"][0]["message"]["content"]
        start, end = content.find("{"), content.rfind("}")
        return json.loads(content[start:end + 1])
    except Exception as exc:  # noqa: BLE001
        print(f"[agent1] LLM 抽取失败（{exc}），改用规则抽取")
        return None


def _rule_extract(text: str) -> Dict:
    skills = extract_skills(text)

    directions: List[str] = []
    for triggers, dirs in DIRECTION_RULES:
        if any(t.lower() in text.lower() for t in triggers):
            directions.extend(d for d in dirs if d not in directions)

    city = next((c for c in CITIES if c in text), "广州")

    salary_min = 4
    m = re.search(r"期望薪资[：: ]*(\d+)\s*[-~]\s*(\d+)\s*[kK]", text)
    if not m:
        m = re.search(r"(\d+)\s*[-~]\s*(\d+)\s*[kK]", text)
    if m:
        salary_min = int(m.group(1))

    school_m = re.search(r"([\u4e00-\u9fa5]{2,12}(?:大学|学院))", text)
    school = school_m.group(1) if school_m else ""

    degree = "本科" if "本科" in text else ("硕士" if "硕士" in text else "本科")

    keywords = directions[:] or ["AI应用"]
    # 关键词补上最值钱的技能，提升搜索命中
    for skill in ("LangChain", "RAG", "MCP"):
        if skill in skills and skill not in keywords and len(keywords) < 5:
            keywords.append(skill)

    return {
        "skills": skills,
        "directions": directions or ["AI应用"],
        "city": city,
        "salary_min": salary_min,
        "degree": degree,
        "school": school,
        "keywords": keywords[:5],
        "years": "应届" if ("应届" in text or "2027" in text) else "不限",
        "summary": f"{city} · {school or degree} · 技能 {len(skills)} 项 · 方向 {'/'.join((directions or ['AI应用'])[:2])}",
    }


MIN_RESUME_LEN = 50


def run(state: dict) -> dict:
    """Agent1 入口：解析简历文本，产出画像与搜索关键词。

    输入太短（空文件 / 扫描件 / 传错）时直接失败，不编造画像——
    否则下游会拿着一份假画像去投递，比报错严重得多。
    """
    text = (state.get("resume_text") or "").strip()
    if len(text) < MIN_RESUME_LEN:
        trace = list(state.get("trace") or [])
        msg = f"简历内容过短（{len(text)} 字，至少 {MIN_RESUME_LEN} 字），可能是空文件或扫描件"
        trace.append(f"Agent1 简历解析失败：{msg}")
        return {"errors": list(state.get("errors") or []) + [f"Agent1: {msg}"], "trace": trace}
    # 规则版保证确定性（76 条词典，含 Agent/Prompt 这类方向词），
    # LLM 版补充简历里出现但词典没收录的技术——两者合并，避免不同模型给出不同画像。
    rule = _rule_extract(text)
    llm = _llm_extract(text)
    if llm:
        merged = list(rule["skills"])
        for s in (llm.get("skills") or []):
            if s and s not in merged:
                merged.append(s)
        profile = {**rule, **{k: v for k, v in llm.items() if v}}
        profile["skills"] = merged
        # 关键词以规则版为准（方向词更稳定），LLM 只在规则版为空时兜底
        profile["keywords"] = rule["keywords"]
        profile["directions"] = rule["directions"] or profile.get("directions") or ["AI应用"]
    else:
        profile = rule

    trace = list(state.get("trace") or [])
    trace.append(
        f"Agent1 简历解析：技能 {len(profile['skills'])} 项 / 方向 {profile['directions']} / "
        f"关键词 {profile['keywords']} / 城市 {profile['city']} / 薪资下限 {profile['salary_min']}K"
    )
    return {"profile": profile, "keywords": profile["keywords"], "trace": trace}
