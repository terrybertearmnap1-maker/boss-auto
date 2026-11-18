"""图节点实现。

每个节点都是 `(state) -> partial_state` 的纯函数，只返回自己负责的字段。
这样节点可以单独测试，也可以随时替换成「调用大模型的版本」而不影响图结构。
"""

import re
from typing import Dict, List

from .state import JobState
from .skills import alternates, display_name, weighted_items

SECTION_KEYS = {
    "职责": ["岗位职责", "工作内容", "职位描述", "岗位描述", "工作职责"],
    "要求": ["任职要求", "岗位要求", "任职资格", "职位要求", "技能要求"],
}

NOISE = re.compile(r"(公司介绍|关于我们|福利待遇|薪资福利|工作地址|联系方式)[^\n]*")


def parse_jd(state: JobState) -> Dict:
    """把 JD 原文切成「职责」「要求」两段，并清掉噪音行。"""
    text = (state.get("jd_text") or "").replace("\r", "")
    text = NOISE.sub("", text)
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]

    sections: Dict[str, str] = {"职责": "", "要求": ""}
    current = None
    for ln in lines:
        hit = None
        for key, headers in SECTION_KEYS.items():
            if any(h in ln for h in headers) and len(ln) <= 12:
                hit = key
                break
        if hit:
            current = hit
            continue
        if current:
            sections[current] += ln + "\n"

    # 没识别出小标题时，退化为全文
    if not sections["职责"] and not sections["要求"]:
        sections["要求"] = text

    trace = list(state.get("trace") or [])
    trace.append(f"parse_jd: 职责 {len(sections['职责'])} 字 / 要求 {len(sections['要求'])} 字")
    return {"sections": sections, "trace": trace}


def extract_skills(state: JobState) -> Dict:
    """从 JD 全文中识别技术关键词（用画像里的同义词组做匹配）。"""
    text = state.get("jd_text") or ""
    profile = state.get("profile") or {}
    found: List[str] = []
    for group, _ in weighted_items(profile):
        if any(re.search(re.escape(a), text, re.IGNORECASE) for a in alternates(group)):
            found.append(display_name(group))

    trace = list(state.get("trace") or [])
    trace.append(f"extract_skills: JD 命中技能 {found or '无'}")
    return {"jd_skills": found, "trace": trace}


def score(state: JobState) -> Dict:
    """按「我的技能被 JD 覆盖的比例」打分，命中排除词直接 0 分。

    注意：排除词只看**岗位标题**，不扫 JD 正文。
    反例——「AI Agent 开发工程师」的正文里常出现「负责后端开发」，
    若扫全文会被「后端」误伤，把高匹配岗位直接判死。
    """
    text = state.get("jd_text") or ""
    title = state.get("title") or ""
    profile = state.get("profile") or {}

    for word in profile.get("exclude", []):
        if word and word.lower() in title.lower():
            trace = list(state.get("trace") or [])
            trace.append(f"score: 标题命中排除词「{word}」→ 0 分")
            return {
                "score": 0, "banned": word, "matched": [], "missing": [],
                "trace": trace,
            }

    items = weighted_items(profile)
    total = sum(w for _, w in items) or 1
    got = 0
    matched, missing = [], []
    for group, weight in items:
        if any(re.search(re.escape(a), text, re.IGNORECASE) for a in alternates(group)):
            got += weight
            matched.append(display_name(group))
        else:
            missing.append(display_name(group))

    value = round(got / total * 100)
    trace = list(state.get("trace") or [])
    trace.append(f"score: {got}/{total} 权重 → {value} 分")
    return {"score": value, "matched": matched, "missing": missing, "trace": trace}


def route(state: JobState) -> str:
    """条件边：过阈值走投递分支，否则走拒绝分支。"""
    threshold = int(state.get("threshold") or 60)
    return "apply" if int(state.get("score") or 0) >= threshold else "skip"


def draft_greeting(state: JobState) -> Dict:
    """按 JD 命中的技能拼一句打招呼语（可替换成 LLM 生成节点）。"""
    title = state.get("title") or "这个岗位"
    company = state.get("company") or "贵司"
    skills = state.get("matched") or []
    top = "、".join(skills[:3]) if skills else "Python 与智能体开发"

    greeting = (
        f"您好，我是27届本科应届生，方向是 AI Agent 应用开发。"
        f"看到{company}的「{title}」，岗位要求里的{top}我都做过，"
        f"也自己搭过一套求职自动化 Agent（JD 解析 + 匹配打分 + 自动跟进）。"
        f"方便聊聊吗？"
    )
    trace = list(state.get("trace") or [])
    trace.append(f"draft_greeting: 已生成（{len(greeting)} 字）")
    return {"decision": "apply", "reason": f"匹配 {state.get('score')} 分，高于阈值",
            "greeting": greeting, "trace": trace}


def reject(state: JobState) -> Dict:
    """拒绝分支：写清原因，便于复盘为什么没投。"""
    score_value = int(state.get("score") or 0)
    banned = state.get("banned")
    if banned:
        reason = f"命中排除词「{banned}」"
    else:
        reason = f"匹配 {score_value} 分，低于阈值 {state.get('threshold')}"
    trace = list(state.get("trace") or [])
    trace.append(f"reject: {reason}")
    return {"decision": "skip", "reason": reason, "greeting": "", "trace": trace}
