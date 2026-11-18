"""P1 验收测试：简历读取 + 结构化画像。

默认用仓库内的脱敏样例（data/resume_sample.txt）。
如果想验证 PDF 解析，设置环境变量 RESUME_PDF 指向本地 PDF 即可。
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents import decide_agent, resume_agent  # noqa: E402
from pipeline.resume_io import ResumeReadError, read_text  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SAMPLE_TXT = ROOT / "data" / "resume_sample.txt"


def main() -> int:
    ok = True

    # 1) 纯文本样例：始终可跑，不依赖任何个人文件
    text = read_text(SAMPLE_TXT)
    print(f"[读取] {len(text)} 字符（样例简历）")
    ok &= len(text) > 100

    profile = resume_agent.run({"resume_text": text, "trace": []})["profile"]
    print("[画像]", {k: profile[k] for k in ("skills", "directions", "city", "salary_min", "degree", "school")})
    ok &= len(profile["skills"]) >= 6
    ok &= "Agent" in profile["directions"]
    ok &= profile["salary_min"] >= 4
    ok &= bool(profile["school"])

    # 2) 话术要带上学校
    job = {"title": "AI Agent 开发工程师", "company": "示例公司", "score": 80,
           "matched": ["Python", "Agent", "MCP"]}
    greeting = decide_agent._template(job, profile)
    print("[话术]", greeting)
    ok &= profile["school"] in greeting

    # 3) 可选：真实 PDF 解析（设了 RESUME_PDF 才跑，避免仓库里存个人简历）
    pdf = os.getenv("RESUME_PDF")
    if pdf and Path(pdf).exists():
        pdf_text = read_text(pdf)
        print(f"[PDF] {len(pdf_text)} 字符")
        ok &= len(pdf_text) > 300
    else:
        print("[PDF] 跳过（未设置 RESUME_PDF，仓库不存放个人简历）")

    # 4) 坏输入必须显式报错
    try:
        read_text(Path(__file__).with_suffix(".txt"))
        ok = False
        print("[FAIL] 不存在的文件没有报错")
    except ResumeReadError as exc:
        print("[异常] 预期内的报错：", str(exc)[:32])

    print("\nP1 验收通过" if ok else "\nP1 验收失败")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
