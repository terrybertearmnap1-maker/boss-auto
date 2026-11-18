"""Agent4：决策 + 话术生成。

判断逻辑：分数 ≥ 阈值就投，否则记录原因（分数不足 / 命中排除词 / 已投过）。
话术按「岗位标题 + 命中的前三个技能」拼，可选接 LLM 改写。
"""

from __future__ import annotations

import os
import re
from typing import Dict, List

from pipeline.envload import load_env

load_env()   # 读取 .env 里的 OPENAI_* 配置

EXCLUDE = ["java", "销售", "标注", "训练师", "客服", "运营"]


_SALARY_TAIL = re.compile(r"\s+\d+(?:\.\d+)?-\d+(?:\.\d+)?\s*(?:[Kk]|万|元)[^\s]*.*$")


def _clean_title(title: str) -> str:
    """去掉标题尾巴上的薪资（如「AI Agent 开发工程师 12-15K·14薪」），只留岗位名。"""
    cleaned = _SALARY_TAIL.sub("", title or "").strip()
    return cleaned or (title or "")


def _known_terms() -> List[str]:
    """全部可能被话术提到的技术名词（取技能词典里的标准名）。"""
    from pipeline.skill_dict import SKILL_GROUPS

    terms: List[str] = []
    for group in SKILL_GROUPS.values():
        for item in group:
            terms.append(item.split("|")[0])
    return terms


def _overclaims(greeting: str, profile: Dict, matched: List[str]) -> List[str]:
    """找出话术里提到、但简历并不具备的技术名词。

    模型很爱说「Django 我也有经验」——这种过度声称在面试时是致命的，
    所以只要出现简历没有的技术，就整句打回模板。
    """
    # 方向词不算"技术栈声称"：说"做过 Agent 项目"不等于声称会某个具体框架
    generic = {"agent", "prompt", "llm", "rag", "大模型", "智能体", "ai应用"}
    mine = {s.lower() for s in (profile.get("skills") or [])} | generic
    mine |= {s.lower() for s in matched}
    mine |= {s.lower() for s in (profile.get("directions") or [])}
    from pipeline.skill_dict import _hit  # 复用词边界匹配，避免 Go 命中 Django、SQL 命中 MySQL

    text = (greeting or "").lower()
    bad = []
    for term in _known_terms():
        t = term.lower()
        if len(t) < 2:
            continue
        if _hit(text, term) and t not in mine:
            bad.append(term)
    return bad


def _project_detail(job: Dict) -> str:
    """按岗位方向挑一句「做过什么」，作为话术中间那段的具体素材。"""
    matched = {s.lower() for s in (job.get("matched") or [])}
    if {"langgraph", "langchain", "智能体", "agent"} & matched:
        return "做过四段式多 Agent 编排（LangGraph 串联，接浏览器扩展做真实投递）"
    if {"rag", "向量数据库", "qdrant", "知识库"} & matched:
        return "做过团队知识库 Agent（分块检索、服务端生成引用、无依据拒答）"
    if {"fastapi", "redis", "mysql", "websocket"} & matched:
        return "做过 FastAPI + WebSocket 流式服务（Redis 会话、多表落库）"
    return "做过 AI 应用开发，从需求拆解到接口联调都走过一遍"


def _template(job: Dict, profile: Dict) -> str:
    """模板话术：三段式 —— JD 技术栈在前、项目细节在中、邀请沟通在后。"""
    matched = [s for s in (job.get("matched") or []) if s][:3]
    missing = [s for s in (job.get("missing") or []) if s][:1]
    skills = "、".join(matched) or "Python 与智能体开发"
    title = _clean_title(job.get("title") or "") or "这个岗位"
    company = job.get("company") or ""
    where = f"贵司「{title}」" if company else f"「{title}」"
    detail = _project_detail(job)
    gap = f"{missing[0]}这块我也在补，" if missing and len(matched) < 2 else ""
    return (
        f"您好，看到{where}要求{skills}，我{detail}；"
        f"{gap}方便聊聊这个岗位的技术方向吗？"
    )


def _llm_greeting(job: Dict, profile: Dict) -> str | None:
    """用模型按「JD 技术栈 → 项目细节 → 邀请」三段写话术。"""
    base, key = os.getenv("OPENAI_BASE_URL"), os.getenv("OPENAI_API_KEY")
    if not base or not key:
        return None
    try:
        import httpx

        prompt = (
            "你在帮一个 2027 届本科生写 BOSS 直聘的打招呼语。严格按三段结构，全文 60-85 字（超了就删修饰词）：\n"
            "第一段：点出这个岗位 JD 里要求的 2-3 个技术——**必须同时出现在下面的「我会的技能」里**，我不会的绝对不许提\n"
            "第二段：用一句话说我做过的、跟这些技术对得上的项目细节——说「做了什么」而不是罗列名词\n"
            "第三段：一句自然的邀请，问这个岗位的技术方向\n\n"
            "禁止：贵公司、尊敬的HR、联系方式、表情符号、「扎实的基础」「学习能力强」这类空话。\n"
            "第一句不超过 30 字，整段读起来像人说话，不像简历。\n"
            "只输出话术本身，不要解释、不要引号。\n\n"
            f"岗位：{_clean_title(job.get('title') or '')} @ {job.get('company', '')}\n"
            f"JD 摘要：{(job.get('jd') or '')[:600]}\n"
            f"我会的技能：{'、'.join((profile.get('skills') or [])[:10])}\n"
            f"可用的项目素材：{_project_detail(job)}"
        )
        resp = httpx.post(
            f"{base.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {key}"},
            json={"model": os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
                  "messages": [{"role": "user", "content": prompt}], "temperature": 0.4},
            timeout=40,
        )
        data = resp.json()
        if "choices" not in data:
            print(f"[agent4] LLM 返回异常：{str(data)[:160]}")
            return None
        text = data["choices"][0]["message"]["content"].strip().strip('"“”')
        return text or None
    except Exception as exc:  # noqa: BLE001
        print(f"[agent4] LLM 生成失败（{exc}），用模板")
        return None


def run(state: dict) -> dict:
    """Agent4 入口：逐个岗位决策，通过的生成话术。"""
    profile = state.get("profile") or {}
    threshold = int(state.get("threshold", 60))
    jobs: List[Dict] = list(state.get("jobs") or [])

    decisions = []
    for job in jobs:
        title = (job.get("title") or "")
        # JD 缺失的岗位不参与决策：既不知道要求，就无法生成可信话术
        if job.get("jd_missing"):
            decisions.append({**job, "decision": "skip", "reason": "JD 缺失，待补抓", "greeting": ""})
            continue
        banned = next((w for w in EXCLUDE if w.lower() in title.lower()), None)

        if banned:
            decisions.append({**job, "decision": "skip", "reason": f"标题命中排除词「{banned}」", "greeting": ""})
            continue
        if int(job.get("score", 0)) < threshold:
            decisions.append({**job, "decision": "skip", "reason": f"匹配 {job['score']} 分，低于阈值 {threshold}", "greeting": ""})
            continue

        template = _template(job, profile)
        llm_text = _llm_greeting(job, profile)
        overclaim = _overclaims(llm_text, profile, job.get("matched") or []) if llm_text else []
        if llm_text and overclaim:
            print(f"[agent4] 话术提到简历没有的技术 {overclaim}，回退模板")
            llm_text = None
        greeting = llm_text or template
        source = "llm" if llm_text else "template"
        # 校验：LLM 话术必须引用命中的技能，否则说明它在编，回退模板
        if source == "llm" and job.get("matched") and not any(s in greeting for s in job["matched"]):
            greeting, source = template, "template(fallback)"
        decisions.append({
            **job, "decision": "apply", "reason": f"匹配 {job['score']} 分",
            "greeting": greeting, "greeting_source": source,
        })

    applied = [d for d in decisions if d["decision"] == "apply"]
    trace = list(state.get("trace") or [])
    trace.append(f"Agent4 决策：投递 {len(applied)} / 跳过 {len(decisions) - len(applied)}（阈值 {threshold}）")
    for d in applied:
        trace.append(f"        · 投递 {d['title']} @ {d['company']}（{d['score']} 分）")
        trace.append(f"          话术：{d['greeting'][:50]}…")
    return {"decisions": decisions, "trace": trace}
