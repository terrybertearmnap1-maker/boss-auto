"""环境体检：迁移到新电脑后跑一条命令，确认各处都到位。

    python -m pipeline.doctor

检查项：Python 版本 / 依赖 / .env / 简历解析结果 / 数据库 / 端口 / 扩展文件。
"""

from __future__ import annotations

import json
import os
import socket
import sys
from pathlib import Path

JOBPILOT = Path(__file__).resolve().parent.parent
REPO = JOBPILOT.parent

OK = "✅"
BAD = "❌"
WARN = "⚠️"


def _line(mark: str, name: str, detail: str = "") -> bool:
    print(f" {mark} {name:<26} {detail}")
    return mark == OK


def check_python() -> bool:
    v = sys.version_info
    good = (v.major, v.minor) >= (3, 10)
    return _line(OK if good else BAD, "Python 版本", f"{v.major}.{v.minor}.{v.micro}")


def check_deps() -> bool:
    missing = []
    for mod in ("fastapi", "uvicorn", "httpx", "langgraph"):
        try:
            __import__(mod)
        except ImportError:
            missing.append(mod)
    if missing:
        return _line(BAD, "Python 依赖", f"缺少 {', '.join(missing)} → pip install -r requirements.txt")
    return _line(OK, "Python 依赖", "fastapi / uvicorn / httpx / langgraph 就位")


def check_env() -> bool:
    from pipeline.envload import llm_ready

    env_file = JOBPILOT / ".env"
    if not env_file.exists():
        return _line(WARN, ".env 配置", "没有 .env，话术会退化成模板（仍可用）")
    if llm_ready():
        model = os.getenv("OPENAI_MODEL", "?")
        return _line(OK, ".env 配置", f"已配置，模型 {model}")
    return _line(WARN, ".env 配置", "有文件但缺 OPENAI_API_KEY")


def check_resume() -> bool:
    from pipeline import resume_store

    cur = resume_store.current()
    if not cur:
        return _line(WARN, "简历解析结果", "没有，去后台上传一次 PDF")
    skills = len((cur.get("profile") or {}).get("skills") or [])
    return _line(OK, "简历解析结果", f"{cur.get('filename')} · 技能 {skills} 项")


def check_db() -> bool:
    db_file = JOBPILOT / "jobpilot.db"
    if not db_file.exists():
        return _line(WARN, "投递数据库", "没有，首次运行会自动创建")
    try:
        import sqlite3

        conn = sqlite3.connect(db_file)
        total = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
        real = conn.execute("SELECT COUNT(*) FROM jobs WHERE source='zhipin'").fetchone()[0]
        conn.close()
        return _line(OK, "投递数据库", f"{total} 条记录（真实岗位 {real} 条）")
    except Exception as exc:  # noqa: BLE001
        return _line(WARN, "投递数据库", f"读取失败：{exc}")


def check_port() -> bool:
    with socket.socket() as s:
        busy = s.connect_ex(("127.0.0.1", 8030)) == 0
    if busy:
        return _line(OK, "后端端口 8030", "已被占用（说明服务在跑）")
    return _line(WARN, "后端端口 8030", "空闲，记得启动 uvicorn")


def check_extension() -> bool:
    manifest = REPO / "extension" / "manifest.json"
    if not manifest.exists():
        return _line(BAD, "浏览器扩展", "找不到 extension/manifest.json")
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
        return _line(OK, "浏览器扩展", f"v{data.get('version')} · 记得在 Chrome 里加载")
    except Exception as exc:  # noqa: BLE001
        return _line(BAD, "浏览器扩展", f"manifest 解析失败：{exc}")


def check_private_repo() -> bool:
    home = Path(os.getenv("BOSS_AUTO_HOME", str(Path.home() / "Documents" / "boss-auto")))
    candidates = [home, Path("D:/boss-auto-local")]
    for path in candidates:
        if (path / "manifest.json").exists():
            return _line(OK, "私密备份目录", str(path))
    return _line(WARN, "私密备份目录", "没找到，可用 python -m pipeline.backup status 查看")


def main() -> int:
    print("boss-auto 环境体检\n" + "=" * 58)
    results = [
        check_python(), check_deps(), check_env(), check_resume(),
        check_db(), check_port(), check_extension(), check_private_repo(),
    ]
    print("=" * 58)
    bad = results.count(False)
    if bad == 0:
        print(f"{OK} 全部通过，环境可用")
    else:
        print(f"{WARN} 有 {bad} 项需要注意（⚠️ 不影响启动，❌ 必须修复）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
