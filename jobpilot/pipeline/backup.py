"""本地私密数据的一键备份 / 恢复。

为什么需要它：这几样东西不能进公开仓库，但换电脑又要带走：
    resume/                    简历成品（PDF/DOCX）
    private/                   简历生成脚本
    jobpilot.db                投递记录与岗位库
    data/current_resume.json   简历解析结果

用法：
    python -m pipeline.backup status                         # 看现在有哪些
    python -m pipeline.backup export D:\\boss-auto-local       # 打包到文件夹
    python -m pipeline.backup import D:\\boss-auto-local       # 从文件夹还原

导出的文件夹丢进私有仓库或网盘同步，换电脑就不用一件件拷。
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Dict, List, Tuple

JOBPILOT = Path(__file__).resolve().parent.parent          # .../boss-auto/jobpilot
REPO = JOBPILOT.parent                                     # .../boss-auto
# 私密数据可能放在仓库外的 Documents\boss-auto 下（避免误提交）
HOME = Path(os.getenv("BOSS_AUTO_HOME", str(Path.home() / "Documents" / "boss-auto")))

# (名称, 候选源路径（按优先级）, 包内相对路径, 还原时的目标路径)
ITEMS: List[Tuple[str, List[Path], str, Path]] = [
    ("简历成品", [REPO / "resume", HOME / "resume"],
     "resume", REPO / "resume"),
    ("简历脚本", [REPO / "private", HOME / "private"],
     "private", REPO / "private"),
    ("投递数据库", [JOBPILOT / "jobpilot.db", HOME / "_local" / "jobpilot.db"],
     "jobpilot/jobpilot.db", JOBPILOT / "jobpilot.db"),
    ("简历解析结果", [JOBPILOT / "data" / "current_resume.json", HOME / "_local" / "current_resume.json"],
     "jobpilot/data/current_resume.json", JOBPILOT / "data" / "current_resume.json"),
]


def _first_existing(candidates: List[Path]) -> Path | None:
    for path in candidates:
        if path.exists():
            return path
    return None


def _copy_file(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def _copy_dir(src: Path, dst: Path) -> int:
    count = 0
    for path in src.rglob("*"):
        if path.is_file():
            _copy_file(path, dst / path.relative_to(src))
            count += 1
    return count


def export(out: Path) -> Dict:
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    items: List[str] = []
    total = 0

    for name, candidates, rel, _target in ITEMS:
        src = _first_existing(candidates)
        if not src:
            items.append(f"{name}: 跳过（找不到）")
            continue
        dst = out / rel
        if src.is_dir():
            n = _copy_dir(src, dst)
            total += n
            items.append(f"{name}: {n} 个文件")
        else:
            _copy_file(src, dst)
            total += 1
            items.append(f"{name}: 1 个文件")

    manifest = {
        "exported_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "repo": str(REPO),
        "files": total,
        "items": items,
    }
    (out / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def restore(src: Path) -> Dict:
    src = Path(src)
    if not (src / "manifest.json").exists():
        raise FileNotFoundError(f"{src} 下没有 manifest.json，不像备份目录")

    stamp = time.strftime("%Y%m%d-%H%M%S")
    items: List[str] = []
    total = 0

    for name, _candidates, rel, target in ITEMS:
        backup = src / rel
        if not backup.exists():
            items.append(f"{name}: 跳过（备份里没有）")
            continue
        if target.exists():
            shutil.move(str(target), f"{target}.bak-{stamp}")
        if backup.is_dir():
            n = _copy_dir(backup, target)
            total += n
            items.append(f"{name}: {n} 个文件")
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            _copy_file(backup, target)
            total += 1
            items.append(f"{name}: 1 个文件")

    return {"restored_at": time.strftime("%Y-%m-%d %H:%M:%S"), "files": total, "items": items}


def status() -> List[Dict]:
    rows = []
    for name, candidates, _rel, _target in ITEMS:
        src = _first_existing(candidates)
        if not src:
            rows.append({"name": name, "exists": False, "path": "", "size": 0})
            continue
        size = (sum(p.stat().st_size for p in src.rglob("*") if p.is_file())
                if src.is_dir() else src.stat().st_size)
        rows.append({"name": name, "exists": True, "path": str(src), "size": size})
    return rows


def main(argv: List[str]) -> int:
    if len(argv) < 2 or argv[1] not in ("export", "import", "status"):
        print(__doc__)
        return 1

    cmd = argv[1]
    if cmd == "status":
        for row in status():
            mark = "✅" if row["exists"] else "—"
            size = f"{row['size'] / 1024:.0f} KB" if row["exists"] else "（找不到）"
            print(f" {mark} {row['name']:<10} {size:<10} {row['path']}")
        return 0

    if len(argv) < 3:
        print("缺少目标目录，例如：python -m pipeline.backup export D:\\boss-auto-local")
        return 1

    path = Path(argv[2])
    if cmd == "export":
        info = export(path)
        print(f"已导出 {info['files']} 个文件 → {path}")
        for item in info["items"]:
            print("  ·", item)
        print("\n把这个目录放进私有仓库或网盘，换电脑用 import 还原。")
    else:
        info = restore(path)
        print(f"已还原 {info['files']} 个文件 ← {path}")
        for item in info["items"]:
            print("  ·", item)
        print("\n覆盖前的旧文件已重命名为 *.bak-时间戳。")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
