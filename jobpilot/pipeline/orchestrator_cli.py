"""四段式 Agent 流水线的命令行入口。

用法：
    python -m pipeline.orchestrator_cli --resume data/resume_sample.txt --limit 6
    python -m pipeline.orchestrator_cli --resume data/resume_sample.txt --threshold 65 --json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import orchestrator

ROOT = Path(__file__).resolve().parent.parent


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--resume", default=str(ROOT / "data" / "resume_sample.txt"))
    ap.add_argument("--threshold", type=int, default=60)
    ap.add_argument("--limit", type=int, default=8)
    ap.add_argument("--json", action="store_true", help="输出完整 JSON（含每条决策）")
    args = ap.parse_args(argv)

    # 支持 PDF / DOCX / TXT：统一在这里读，下游 Agent 只拿文本
    from .resume_io import read_text

    try:
        text = read_text(args.resume)
    except Exception as exc:  # noqa: BLE001
        print(f"[简历读取失败] {exc}", file=sys.stderr)
        return 2
    result = orchestrator.run_pipeline(text, threshold=args.threshold, limit=args.limit)

    if args.json:
        print(json.dumps({
            "profile": result["profile"],
            "decisions": [
                {k: d.get(k) for k in ("job_id", "title", "company", "salary", "score", "decision", "reason", "greeting")}
                for d in result["decisions"]
            ],
            "elapsed_ms": result["elapsed_ms"],
        }, ensure_ascii=False, indent=2))
        return 0

    print("=" * 70)
    for line in result["trace"]:
        print(line)
    print("=" * 70)
    applied = [d for d in result["decisions"] if d["decision"] == "apply"]
    print(f"流水线耗时 {result['elapsed_ms']} ms｜投递 {len(applied)} / 评估 {len(result['decisions'])}")
    for d in applied:
        print(f"\n【投递】{d['title']} @ {d['company']}（{d['salary']}）— {d['score']} 分")
        print(f"  话术：{d['greeting']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
