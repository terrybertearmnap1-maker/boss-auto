import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

RESUME = str(Path(__file__).resolve().parent.parent / "data" / "resume_sample.txt")

from pipeline.orchestrator import run_pipeline
from pipeline.resume_io import read_text

res = run_pipeline(read_text(RESUME), threshold=60, limit=12)
print(f"{'分':>3} | {'决策':<5} | {'职位':<26} | 扣分 / 原因")
print("-" * 78)
for d in res["decisions"]:
    reasons = ",".join(d.get("penalty_reasons") or [])
    print(f"{d['score']:>3} | {d['decision']:<5} | {d['title'][:26]:<26} | {d.get('penalty', 0)} {reasons}")
print("-" * 78)
print("errors:", res.get("errors"))
