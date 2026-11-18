"""Agent2：岗位搜索。

真实环境里，这个 Agent 的工具是「浏览器扩展」——它把关键词发给打开着 BOSS 的页面，
页面执行搜索并把岗位列表回传（WebSocket 双向）。

为了让整条流水线在没有任何浏览器的情况下也能跑通，这里提供一个
`LocalIndexSearch` 实现：用本地岗位索引模拟 BOSS 的搜索结果。
两者遵循同一个接口 `search(keywords, city, salary_min) -> list[dict]`，
接扩展时只换实现，不动编排。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, List

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def parse_salary(text: str):
    """'12-20K' → (12, 20)；'150-250元/天' → (3.3, 5.5) 按月 22 天折算。"""
    t = (text or "").replace(" ", "")
    m = re.search(r"(\d+(?:\.\d+)?)-(\d+(?:\.\d+)?)[Kk]", t)
    if m:
        return float(m.group(1)), float(m.group(2))
    m = re.search(r"(\d+)-(\d+)元/天", t)
    if m:
        return round(int(m.group(1)) * 22 / 1000, 1), round(int(m.group(2)) * 22 / 1000, 1)
    return None


class LocalIndexSearch:
    """本地索引实现：过滤关键词 + 城市 + 薪资下限。"""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path else DATA_DIR / "jobs_index.json"
        self.jobs: List[Dict] = json.loads(self.path.read_text(encoding="utf-8"))

    def search(self, keywords: List[str], city: str = "", salary_min: int = 0,
               limit: int = 10) -> List[Dict]:
        hit = []
        for job in self.jobs:
            blob = f"{job.get('title','')} {job.get('company','')} {job.get('jd','')}"
            if keywords and not any(k and k.lower() in blob.lower() for k in keywords):
                continue
            # 城市只看专门的 city 字段；JD 正文里没写城市不代表城市不符
            job_city = job.get("city", "")
            if city and job_city and city not in job_city:
                continue
            rng = parse_salary(job.get("salary", ""))
            if rng and rng[1] < salary_min:
                continue
            hit.append(job)
            if len(hit) >= limit:
                break
        # 一个都没命中时，退化为「只按第一个关键词」再搜一次
        # 注意必须加 len>1 判断，否则单关键词时「退化后还是空」会无限递归
        if not hit and len(keywords) > 1:
            return self.search(keywords[:1], city="", salary_min=salary_min, limit=limit)
        return hit


class BrowserHallSearch:
    """读扩展刚刚上报的岗位批次（生产环境的真实数据来源）。

    与 LocalIndexSearch 同签名，编排层不感知差异。
    批次过期（默认 15 分钟）就返回空，调用方自动回退本地索引。
    """

    def __init__(self, max_age: int = 900) -> None:
        self.max_age = max_age

    def search(self, keywords: List[str], city: str = "", salary_min: int = 0,
               limit: int = 10) -> List[Dict]:
        from pipeline import search_hub

        batch = search_hub.get(max_age=self.max_age)
        if not batch:
            return []
        jobs = []
        for job in batch["jobs"]:
            blob = f"{job.get('title','')} {job.get('company','')} {job.get('jd','')}"
            if keywords and not any(k and k.lower() in blob.lower() for k in keywords):
                continue
            job_city = job.get("city", "") or batch.get("city", "")
            if city and job_city and city not in job_city:
                continue
            jobs.append(job)
            if len(jobs) >= limit:
                break
        return jobs


class RecentJobsSearch:
    """读「扩展最近上报过的真实岗位」作为搜索结果。

    数据来自 POST /ingest（扩展访问详情页时上报，含真实 JD + 分数）。
    好处：不改浏览器侧任何代码就能让 Agent2 吃到真实数据。
    """

    def __init__(self, limit_days: int = 7) -> None:
        self.limit_days = limit_days

    def search(self, keywords: List[str], city: str = "", salary_min: int = 0,
               limit: int = 10) -> List[Dict]:
        from pipeline.api import db

        rows = db.list_jobs(limit=200) or []
        jobs = []
        for row in rows:
            jd = (row.get("jd") or "").strip()
            if not jd:
                continue
            # 只认「扩展从招聘站抓回来的」岗位；
            # agent-pipeline / cli 是流水线自己写进去的，否则会把自己输出再当输入（自循环）
            if row.get("source") not in ("zhipin",):
                continue
            job = {
                "job_id": row.get("job_id", ""),
                "title": row.get("title", ""),
                "company": row.get("company", ""),
                "salary": row.get("salary", ""),
                "url": row.get("url", ""),
                "city": "",
                "jd": jd,
                "source": row.get("source", "zhipin"),
            }
            blob = f"{job['title']} {job['company']} {jd}"
            if keywords and not any(k and k.lower() in blob.lower() for k in keywords):
                continue
            rng = parse_salary(job["salary"])
            if rng and salary_min and rng[1] < salary_min:
                continue
            jobs.append(job)
            if len(jobs) >= limit:
                break
        return jobs


MIN_RESULTS = 6  # 粗筛命中少于此数就放宽条件补量


def run(state: dict, tool=None) -> dict:
    """Agent2 入口：两段式搜索。

    第一段按关键词粗筛；命中不足 `min_results` 条时，第二段放宽到「城市 + 薪资」，
    把够格但标题没写关键词的岗位也捞进来——评分留给 Agent3，不在这里提前判死。
    """
    profile = state.get("profile") or {}
    search = tool or LocalIndexSearch()
    keywords = state.get("keywords") or profile.get("keywords", [])
    city = profile.get("city", "")
    salary_min = int(profile.get("salary_min", 0))
    limit = int(state.get("limit", 8))
    need = int(state.get("min_results", MIN_RESULTS))

    primary = search.search(keywords=keywords, city=city, salary_min=salary_min, limit=limit)
    relaxed_count = 0
    jobs = list(primary)

    if len(primary) < need:
        # 放宽：不带关键词，只保留城市 + 薪资约束
        wider = search.search(keywords=[], city=city, salary_min=salary_min, limit=limit * 2)
        seen = {j.get("job_id") for j in jobs}
        for job in wider:
            if job.get("job_id") in seen:
                continue
            job = {**job, "relaxed": True}
            jobs.append(job)
            seen.add(job.get("job_id"))
            relaxed_count += 1
            if len(jobs) >= limit:  # limit 是硬上限，need 只用来决定「要不要放宽」
                break

    trace = list(state.get("trace") or [])
    trace.append(
        f"Agent2 岗位搜索：关键词 {keywords} → 粗筛 {len(primary)} 个"
        + (f"，命中不足 {need}，放宽后补 {relaxed_count} 个" if relaxed_count else "")
        + f"，共 {len(jobs)} 个"
    )
    for j in jobs[:6]:
        flag = "（放宽）" if j.get("relaxed") else ""
        trace.append(f"        · {j['title']} @ {j['company']}（{j.get('salary','')}）{flag}")
    return {"jobs": jobs, "trace": trace}

