# -*- coding: utf-8 -*-
"""打一个「推到 GitHub 就能出 ipa」的仓库包：
.github/workflows/ios-ipa.yml + work/ios/**（不含 build/out/dist/__pycache__）。
"""
import sys, zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "out" / "SuperLocator-repo.zip"
SKIP = {"build", "out", "dist", "__pycache__", ".git"}
count = 0
with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
    z.write(ROOT / "ci" / "ios-ipa.yml", ".github/workflows/ios-ipa.yml")
    count += 1
    for p in sorted(ROOT.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(ROOT)
        if any(part in SKIP for part in rel.parts):
            continue
        if p.name.endswith((".pyc", ".log")):
            continue
        z.write(p, Path("work/ios") / rel)
        count += 1
print(f"{OUT.name}: {count} 文件, {OUT.stat().st_size} 字节")
with zipfile.ZipFile(OUT) as z:
    print("testzip:", "OK" if z.testzip() is None else "BAD")
