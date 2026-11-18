"""直接调 decide_agent，看每个岗位 LLM 是否成功、被哪些词判为过度声称。"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402

from agents import decide_agent, match_agent, search_agent  # noqa: E402
from pipeline import resume_store, search_hub  # noqa: E402
from pipeline.orchestrator import run_pipeline  # noqa: E402

text = resume_store.text()
if not text:
    raise SystemExit("先上传简历")

state = run_pipeline(text, threshold=60, limit=4, tool=search_agent.LocalIndexSearch())
profile = state["profile"]
jobs = state["jobs"]

print("profile 技能:", "、".join(profile["skills"]))
print()
for job in jobs:
    llm = decide_agent._llm_greeting(job, profile)
    if not llm:
        print(f"· {job['title'][:28]} → LLM 无返回")
        continue
    bad = decide_agent._overclaims(llm, profile, job.get("matched") or [])
    flag = "✅ 通过" if not bad else f"❌ 过度声称 {bad}"
    print(f"· {job['title'][:28]} → {flag}")
    print(f"   {llm[:90]}")
