"""P6 指令队列测试：入队去重 / 取走 / ack / 状态统计。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline import commands  # noqa: E402


def main() -> int:
    ok = True
    commands.clear()

    # 1) 入队
    made = commands.enqueue([
        {"job_id": "a", "title": "岗A", "company": "甲", "url": "u-a", "greeting": "话术A"},
        {"job_id": "b", "title": "岗B", "company": "乙", "url": "u-b", "greeting": "话术B"},
    ])
    print(f"[入队] {len(made)} 条")
    ok &= len(made) == 2

    # 2) 重复 job_id 不重复入队
    again = commands.enqueue([{"job_id": "a", "title": "岗A", "url": "u-a"}])
    print(f"[去重] 重复入队 {len(again)} 条（应为 0）")
    ok &= len(again) == 0

    # 3) 取走 → inflight
    got = commands.pop(1)
    print(f"[取走] {len(got)} 条，剩余 queued={commands.stats()['queued']} inflight={commands.stats()['inflight']}")
    ok &= len(got) == 1 and commands.stats()["inflight"] == 1

    # 4) 取走后同一 job 不应被再次入队（还在 inflight）
    dup = commands.enqueue([{"job_id": got[0]["job"]["job_id"], "title": "重复"}])
    ok &= len(dup) == 0

    # 5) ack
    acked = commands.ack(got[0]["id"], True, "")
    print(f"[ack] {acked}，done={commands.stats()['done']} ok={commands.stats()['ok']}")
    ok &= acked and commands.stats()["ok"] == 1

    # 6) 重复 ack 应返回 False
    ok &= commands.ack(got[0]["id"], True, "") is False

    # 7) 失败也要能记录
    second = commands.pop(1)[0]
    commands.ack(second["id"], False, "发送失败")
    st = commands.stats()
    print(f"[失败] failed={st['failed']}，最近一条 reason={st['recent'][-1]['reason']}")
    ok &= st["failed"] == 1 and st["recent"][-1]["reason"] == "发送失败"

    commands.clear()
    print("\nP6 指令队列测试通过" if ok else "\nP6 指令队列测试失败")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
