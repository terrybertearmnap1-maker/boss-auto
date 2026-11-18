"""技能词典回归测试：规模 + 同义词 + 误匹配。

误匹配是这类词典最容易翻车的地方，必须用测试锁住，
否则以后加词时一个 `Go` 就能把 `Google` 全带进来。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.skill_dict import extract_skills, stats  # noqa: E402


def check(name: str, cond: bool, detail: str = "") -> bool:
    print(f"[{'PASS' if cond else 'FAIL'}] {name}{' — ' + detail if detail and not cond else ''}")
    return cond


def main() -> int:
    ok = True

    st = stats()
    print(f"[规模] {st['groups']} 组 / {st['terms']} 个词条")
    ok &= check("词条数 ≥ 60", st["terms"] >= 60, str(st))
    ok &= check("分组数 ≥ 5", st["groups"] >= 5, str(st))

    # 应命中
    ok &= check("Golang → Go", "Go" in extract_skills("熟悉 Golang 开发"))
    ok &= check("K8s → Kubernetes", "Kubernetes" in extract_skills("用 K8s 部署"))
    ok &= check("大模型 → LLM", "LLM" in extract_skills("做过大模型应用"))
    ok &= check("智能体 → Agent", "Agent" in extract_skills("智能体开发"))
    ok &= check("Cursor 被识别", "Cursor" in extract_skills("用 Cursor 写代码"))
    ok &= check("工具调用 → Function Calling",
                "Function Calling" in extract_skills("实现了工具调用"))

    # 不应命中（误匹配）
    ok &= check("Go 不命中 Google", "Go" not in extract_skills("在 Google 实习"))
    ok &= check("Go 不命中 Django", "Go" not in extract_skills("写过 Django 后端"))
    ok &= check("React 不命中 Reactive", "React" not in extract_skills("Reactive 编程"))
    ok &= check("Spring 不命中 Springfield", not any(
        s.startswith("Spring") for s in extract_skills("Springfield 项目")))

    # 中文简历常见写法
    cn = "熟悉Python和LangGraph，了解向量数据库与提示词工程，用过Docker和Redis"
    got = extract_skills(cn)
    print(f"[中文] {got}")
    ok &= check("中文句子里能认出关键技能",
                {"Python", "LangGraph", "Docker", "Redis"}.issubset(set(got)))

    print("\n技能词典测试通过" if ok else "\n技能词典测试失败")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
