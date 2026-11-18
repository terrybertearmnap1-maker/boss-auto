"""命令行入口：批量评估岗位并输出 CSV。

用法：
    python -m jobgraph.cli --input data/sample_jds.json --out out/decision.csv --threshold 60
"""

import argparse
import csv
import json
import sys
from pathlib import Path

from .graph import build_graph
from .skills import load_profile

ROOT = Path(__file__).resolve().parent.parent


def main(argv=None):
    parser = argparse.ArgumentParser(description="LangGraph 求职决策流程")
    parser.add_argument("--input", default=str(ROOT / "data" / "sample_jds.json"))
    parser.add_argument("--profile", default=str(ROOT / "data" / "profile.json"))
    parser.add_argument("--out", default=str(ROOT / "out" / "decision.csv"))
    parser.add_argument("--threshold", type=int, default=60)
    parser.add_argument("--verbose", action="store_true", help="打印每个节点轨迹")
    args = parser.parse_args(argv)

    jobs = json.loads(Path(args.input).read_text(encoding="utf-8"))
    profile = load_profile(args.profile)
    app = build_graph(threshold=args.threshold)

    rows = []
    for idx, job in enumerate(jobs):
        init = {
            "title": job.get("title", ""),
            "company": job.get("company", ""),
            "salary": job.get("salary", ""),
            "jd_text": job.get("jd_text", ""),
            "threshold": args.threshold,
            "profile": profile,
            "trace": [],
        }
        config = {"configurable": {"thread_id": f"job-{idx}"}}
        final = app.invoke(init, config=config)

        rows.append({
            "职位": final.get("title", ""),
            "公司": final.get("company", ""),
            "薪资": final.get("salary", ""),
            "匹配分": final.get("score", 0),
            "决策": final.get("decision", ""),
            "原因": final.get("reason", ""),
            "命中技能": " / ".join(final.get("matched", [])),
            "缺失技能": " / ".join(final.get("missing", [])),
            "打招呼语": final.get("greeting", ""),
        })

        if args.verbose:
            print(f"\n=== {final.get('title')} ===")
            for line in final.get("trace", []):
                print("  ", line)
            print(f"   决策：{final.get('decision')}（{final.get('reason')}）")

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    applied = sum(1 for r in rows if r["决策"] == "apply")
    print(f"\n共评估 {len(rows)} 个岗位，投递 {applied} 个，跳过 {len(rows) - applied} 个")
    print(f"结果已写入 {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
