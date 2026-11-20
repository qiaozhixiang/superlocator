#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把编译产物收拢到 dist/，并按需清理中间物

用法：
  # 1) 只收拢产物（不删任何东西），适合先看会收哪些文件
  python work/ios/tools/package_dist.py --ipa build/SuperLocator-unsigned.ipa \
      --tipa build/SuperLocator.tipa --exe build/exe/superlocator.exe

  # 2) 收拢 + 清理（真删，需 --yes）
  python work/ios/tools/package_dist.py --ipa build/SuperLocator-unsigned.ipa --prune --yes

  # 3) 连源码一起清掉，只留 dist/（彻底版）
  python work/ios/tools/package_dist.py --ipa build/SuperLocator-unsigned.ipa --prune --prune-sources --yes

清理范围（--prune）：
  work/ios/build/            PyInstaller 中间物、dd、临时 ipa
  work/ios/out/              历史 kit 压缩包
  各目录 __pycache__
  work/ios/*.log
--prune-sources 另加：
  work/ios/companion/ work/ios/SuperLocator/ work/ios/tools/ work/ios/ci/
  work/ios/*.md（把 README/INSTALL/TROLLSTORE 一并视为「下载物」）
产物一律保留：dist/ 下的 *.ipa/*.tipa/*.exe/*.zip 与 dist/SHA256SUMS.txt
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"

PRUNE_DIRS = [
    ROOT / "build",
    ROOT / "out",
    ROOT / "companion" / "__pycache__",
    ROOT / "companion" / "tests" / "__pycache__",
    ROOT / "tools" / "__pycache__",
]
SOURCE_DIRS = [
    ROOT / "companion",
    ROOT / "SuperLocator",
    ROOT / "tools",
    ROOT / "ci",
]
SOURCE_FILES = ["README.md", "INSTALL.md", "TROLLSTORE.md"]


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


def size_of(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    total = 0
    for p in path.rglob("*"):
        if p.is_file():
            total += p.stat().st_size
    return total


def collect(paths: list[Path]) -> list[Path]:
    DIST.mkdir(parents=True, exist_ok=True)
    moved: list[Path] = []
    for src in paths:
        if not src.is_file():
            print(f"  ! 跳过（不存在）：{src}")
            continue
        dst = DIST / src.name
        if dst.exists() and dst.resolve() == src.resolve():
            moved.append(dst)
            continue
        shutil.copy2(src, dst)
        moved.append(dst)
        print(f"  -> {dst.name}  {human(dst.stat().st_size)}")
    return moved


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ipa", action="append", default=[], help="可多次给")
    ap.add_argument("--tipa", action="append", default=[])
    ap.add_argument("--exe", action="append", default=[])
    ap.add_argument("--zip", action="append", default=[])
    ap.add_argument("--prune", action="store_true", help="删除中间物")
    ap.add_argument("--prune-sources", action="store_true", help="连源码一起删，只留 dist/")
    ap.add_argument("--yes", action="store_true", help="确认执行删除")
    ap.add_argument("--json", action="store_true", help="输出 JSON 汇总")
    args = ap.parse_args()

    given = [Path(x) for x in args.ipa + args.tipa + args.exe + args.zip]
    print(f"收拢 {len(given)} 个产物 -> {DIST}")
    collect(given)
    # 清单始终覆盖 dist/ 里的全部产物，避免「这次只传一个文件就把别的条目抹掉」
    keep_suffix = {".ipa", ".tipa", ".exe", ".zip", ".dmg", ".pkg"}
    kept = sorted(p for p in DIST.iterdir() if p.is_file() and p.suffix in keep_suffix)

    manifest = {
        "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "files": [{"name": p.name, "bytes": p.stat().st_size, "sha256": sha256(p)} for p in kept],
    }
    (DIST / "SHA256SUMS.txt").write_text(
        "".join(f"{f['sha256']}  {f['name']}\n" for f in manifest["files"]), encoding="utf-8")
    (DIST / "MANIFEST.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    removed: list[str] = []
    if args.prune:
        targets = list(PRUNE_DIRS)
        if args.prune_sources:
            targets += SOURCE_DIRS
            targets += [ROOT / f for f in SOURCE_FILES]
        targets += list(ROOT.glob("*.log"))
        plan = [(t, size_of(t)) for t in targets if t.exists()]
        total = sum(s for _, s in plan)
        print(f"\n待清理 {len(plan)} 项，合计 {human(total)}：")
        for t, s in plan:
            print(f"  - {t.relative_to(ROOT)}  {human(s)}")
        if not args.yes:
            print("\n未加 --yes，以上只是清单，没有删任何东西。")
        else:
            for t, _ in plan:
                if t.is_dir():
                    shutil.rmtree(t, ignore_errors=True)
                else:
                    try:
                        t.unlink()
                    except OSError:
                        pass
                removed.append(str(t.relative_to(ROOT)))
            print(f"\n已删除 {len(removed)} 项。")

    left = sorted(p.name for p in ROOT.rglob("*") if p.is_file() and DIST not in p.parents)
    print("\ndist/ 内容：")
    for f in manifest["files"]:
        print(f"  {f['name']}  {human(f['bytes'])}  {f['sha256'][:16]}…")
    print(f"\nwork/ios 下其余文件 {len(left)} 个" + ("" if left else "（已清空）"))
    if args.json:
        print(json.dumps({"kept": manifest["files"], "removed": removed, "left": left[:50]},
                         ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())