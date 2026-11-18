"""P5 验收测试：单个 Agent 失败不能拖垮整条流水线。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.orchestrator import run_pipeline  # noqa: E402

RESUME = (Path(__file__).resolve().parent.parent / "data" / "resume_sample.txt").read_text(encoding="utf-8")


class ExplodingSearch:
    """模拟「扩展掉线 / 搜索接口炸了」。"""

    def search(self, **kwargs):
        raise RuntimeError("extension bridge offline")


def main() -> int:
    ok = True

    # 1) 正常路径
    good = run_pipeline(RESUME, threshold=60, limit=5)
    print(f"[正常] 决策 {len(good['decisions'])} 条，errors={good.get('errors')}")
    ok &= len(good["decisions"]) > 0 and not good.get("errors")

    # 2) 搜索工具炸了 → 不抛异常，错误被记录
    bad = run_pipeline(RESUME, threshold=60, limit=5, tool=ExplodingSearch())
    print(f"[故障] 决策 {len(bad['decisions'])} 条，errors={bad.get('errors')}")
    ok &= bad["decisions"] == []
    ok &= any("Agent2" in e for e in (bad.get("errors") or []))
    ok &= any("失败" in line for line in bad.get("trace", []))

    # 3) 空简历 → Agent1 不炸，后续拿到空数据正常收尾
    empty = run_pipeline("", threshold=60, limit=5)
    print(f"[空简历] 决策 {len(empty.get('decisions', []))} 条，errors={empty.get('errors')}")
    ok &= empty.get("decisions") == []
    ok &= bool(empty.get("errors"))   # 必须显式报错，不能静默返回空画像

    print("\nP5 验收通过" if ok else "\nP5 验收失败")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
