"""Agent3：抓取 JD 并与简历做匹配。

匹配分 = 0.7 × 技能覆盖 + 0.3 × 语义相似 + 硬性条件扣分

三条设计原则：
1. **JD 抓不到时不能当 0 分**——那是「不知道」，不是「不匹配」。标 `jd_missing` 跳过打分，
   由下游标记为「待补抓」，避免整批被误杀（早期版本在这里把全部岗位刷掉过）。
2. **硬性条件要扣分**——JD 写「3-5 年」「硕士」，应届本科就是硬伤，不该只靠技能词掩盖。
3. **分数必须可解释**——每条都带 matched / missing / coverage / semantic / penalties，
   调参和面试复盘都靠它。
"""

from __future__ import annotations

import re
from typing import Dict, List

from pipeline.vectors import cosine, embed

CORE = ["Python", "Agent", "大模型", "LangChain", "MCP", "RAG", "智能体", "LLM"]
BONUS = ["FastAPI", "Redis", "Qdrant", "WebSocket", "Docker", "React", "MySQL", "SQL"]
CORE_W, BONUS_W = 3, 1

MIN_JD_LEN = 30


def parse_experience(jd: str):
    """从 JD 里抽年限要求，返回最低年限；应届/不限返回 0。"""
    if re.search(r"应届|经验不限|在校", jd):
        return 0
    m = re.search(r"(\d+)\s*[-~]\s*(\d+)\s*年", jd)
    if m:
        return int(m.group(1))
    m = re.search(r"(\d+)\s*年以上", jd)
    if m:
        return int(m.group(1))
    return 0


def parse_degree(jd: str) -> str:
    if "硕士" in jd or "研究生" in jd:
        return "硕士"
    if "博士" in jd:
        return "博士"
    if "本科" in jd:
        return "本科"
    return "不限"


def hard_penalty(jd: str, profile: Dict) -> Dict:
    """硬性条件不符时的扣分，返回 {penalty, reasons}。"""
    penalty = 0
    reasons: List[str] = []

    need_years = parse_experience(jd)
    mine_years = 0 if profile.get("years") in ("应届", "不限", "") else 1
    if need_years >= 3 and mine_years < need_years:
        penalty += 15
        reasons.append(f"要求 {need_years} 年以上经验")
    elif need_years == 2 and mine_years < 2:
        penalty += 8
        reasons.append("要求 2 年经验")

    need_deg = parse_degree(jd)
    my_deg = profile.get("degree", "本科")
    if need_deg == "博士" and my_deg != "博士":
        penalty += 25
        reasons.append("要求博士")
    elif need_deg == "硕士" and my_deg == "本科":
        penalty += 15
        reasons.append("要求硕士")

    return {"penalty": penalty, "reasons": reasons}


def skill_coverage(resume_text: str, jd: str) -> Dict:
    """算「JD 要求里我满足了多少」。

    分母是 **JD 提到的技能**，不是我的技能全集——
    否则只要 JD 少写几项，再匹配的人也拿不到高分（早期版本踩过这个坑）。
    """
    items = [(s, CORE_W) for s in CORE] + [(s, BONUS_W) for s in BONUS]
    jd_total = 0
    got = 0
    matched, missing = [], []
    for skill, weight in items:
        if skill.lower() not in jd.lower():
            continue
        jd_total += weight
        if skill.lower() in resume_text.lower():
            got += weight
            matched.append(skill)
        else:
            missing.append(skill)
    return {
        "coverage": round(got / jd_total * 100, 1) if jd_total else 0.0,
        "matched": matched,
        "missing": missing,
        "jd_skill_count": jd_total,
    }


def run(state: dict) -> dict:
    """Agent3 入口：对每个岗位算匹配分，缺失 JD 的单独标记。"""
    resume_text = state.get("resume_text") or ""
    profile = state.get("profile") or {}
    jobs: List[Dict] = list(state.get("jobs") or [])
    resume_vec = embed(resume_text)

    scored: List[Dict] = []
    missing_jd: List[Dict] = []

    for job in jobs:
        jd = (job.get("jd") or "").strip()
        if len(jd) < MIN_JD_LEN:
            # 抓不到 JD：不猜分数，标记待补抓，交给下游跳过
            missing_jd.append({**job, "jd_missing": True, "score": None})
            continue

        cov = skill_coverage(resume_text, jd)
        semantic = max(0.0, cosine(resume_vec, embed(jd))) * 100
        hp = hard_penalty(jd, profile)

        raw = 0.7 * cov["coverage"] + 0.3 * semantic
        score = max(0, min(100, round(raw - hp["penalty"])))

        scored.append({
            **job,
            "jd_missing": False,
            "score": score,
            "matched": cov["matched"],
            "missing": cov["missing"],
            "coverage": cov["coverage"],
            "semantic": round(semantic, 1),
            "penalty": hp["penalty"],
            "penalty_reasons": hp["reasons"],
        })

    scored.sort(key=lambda x: x["score"], reverse=True)
    all_jobs = scored + missing_jd

    trace = list(state.get("trace") or [])
    trace.append(
        f"Agent3 JD 匹配：打分 {len(scored)} 个，JD 缺失 {len(missing_jd)} 个（跳过打分，不按 0 分处理）"
    )
    for job in scored[:5]:
        detail = f"技能 {job['coverage']}% + 语义 {job['semantic']}"
        if job["penalty"]:
            detail += f" − 扣分 {job['penalty']}（{'/'.join(job['penalty_reasons'])}）"
        trace.append(f"        · {job['title']} → {job['score']} 分（{detail}）")
    for job in missing_jd:
        trace.append(f"        · {job['title']} → JD 缺失，待补抓")

    return {"jobs": all_jobs, "trace": trace}
