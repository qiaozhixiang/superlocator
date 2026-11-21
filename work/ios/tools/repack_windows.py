# -*- coding: utf-8 -*-
"""把新编出来的 onedir 产物装配进 dist/SuperLocator-windows 并重新打 zip。

用法：python tools/repack_windows.py build/exe3/superlocator
"""
import hashlib
import os
import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
WIN = DIST / "SuperLocator-windows"
ZIP = DIST / "SuperLocator-windows.zip"


def main(src: str) -> int:
    src_dir = Path(src).resolve()
    if not (src_dir / "superlocator.exe").exists():
        print(f"没找到 {src_dir / 'superlocator.exe'}")
        return 2

    WIN.mkdir(parents=True, exist_ok=True)
    # 只替换程序本体，保留 license/ 与 bat、README
    for name in ("_internal",):
        target = WIN / name
        if target.exists():
            shutil.move(str(target), str(target) + ".old")
            shutil.rmtree(str(target) + ".old", ignore_errors=True)
        shutil.copytree(src_dir / name, target)
    shutil.copy2(src_dir / "superlocator.exe", WIN / "superlocator.exe")
    for extra in src_dir.glob("*.pyd"):
        shutil.copy2(extra, WIN / extra.name)
    print(f"已装配 {WIN}")

    if ZIP.exists():
        os.remove(ZIP)
    total = 0
    with zipfile.ZipFile(ZIP, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for p in sorted(WIN.rglob("*")):
            rel = p.relative_to(WIN).as_posix()
            if rel.startswith("tmp/") or rel.endswith(".log"):
                continue
            if p.is_file():
                z.write(p, rel)
                total += 1
    size = ZIP.stat().st_size
    h = hashlib.sha256(ZIP.read_bytes()).hexdigest()
    print(f"zip: {total} 文件 / {size:,} 字节 / sha256 {h}")
    print(f"路径: {ZIP}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "build/exe3/superlocator"))