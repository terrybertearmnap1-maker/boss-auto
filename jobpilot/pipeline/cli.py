"""命令行：把岗位数据批量灌进 pipeline（走与扩展相同的 /ingest 逻辑）。

用法：
    python -m pipeline.cli --file data/sample_jobs.json
    python -m pipeline.cli --file xxx.csv --threshold 65
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

from . import graph
from .api import cache, db, vectors
from .config import CONFIG


def load(path: Path) -> list[dict]:
    if path.suffix.lower() == ".json":
        return json.loads(path.read_text(encoding="utf-8"))
    rows = []
    with path.open(encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            rows.append({
                "job_id": row.get("job_id") or row.get("链接") or row.get("url", "")[-24:] or str(len(rows)),
                "title": row.get("title") or row.get("职位", ""),
                "company": row.get("company") or row.get("公司", ""),
                "salary": row.get("salary") or row.get("薪资", ""),
                "url": row.get("url") or row.get("链接", ""),
                "jd": row.get("jd") or row.get("JD摘要", ""),
            })
    return rows


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", required=True)
    parser.add_argument("--threshold", type=int, default=CONFIG.score_threshold)
    args = parser.parse_args(argv)

    jobs = load(Path(args.file))
    applied = skipped = 0
    for job in jobs:
        if cache.seen(job["job_id"]):
            skipped += 1
            continue
        neighbor, sim = vectors.nearest(job.get("jd", ""))
        if neighbor and sim >= CONFIG.dedup_threshold:
            cache.mark(job["job_id"])
            skipped += 1
            continue

        final = graph.evaluate(job, args.threshold)
        db.upsert({
            "job_id": job["job_id"], "title": job.get("title", ""), "company": job.get("company", ""),
            "salary": job.get("salary", ""), "url": job.get("url", ""), "source": "cli",
            "score": final.get("score", 0), "decision": final.get("decision", "skip"),
            "reason": final.get("reason", ""), "matched": " / ".join(final.get("matched", [])),
            "greeting": final.get("greeting", ""), "jd": (job.get("jd") or "")[:4000],
        })
        cache.mark(job["job_id"])
        if job.get("jd"):
            vectors.add(job["job_id"], job["jd"])
        if final.get("decision") == "apply":
            applied += 1
            cache.incr_daily()
        else:
            skipped += 1

    print(f"导入 {len(jobs)} 条：投递 {applied}，跳过 {skipped}")
    print("统计：", {**db.stats(), "today": cache.daily_count()})
    return 0


if __name__ == "__main__":
    sys.exit(main())
