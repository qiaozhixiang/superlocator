#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 work/ios 打成可分发的源码+工具包（不含 build/、out/、dist/）

用法：python work/ios/tools/make_kit.py [--out out/SuperLocator-ios-kit.zip]
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {"build", "out", "dist", "__pycache__", ".git", ".venv"}
SKIP_SUFFIX = {".pyc", ".log"}
PREFIX = "SuperLocator-ios"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=ROOT / "out" / "SuperLocator-ios-kit.zip")
    args = ap.parse_args()
    out = args.out if args.out.is_absolute() else ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)

    files = []
    for p in sorted(ROOT.rglob("*")):
        rel = p.relative_to(ROOT)
        if p.is_dir():
            continue
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        if p.suffix in SKIP_SUFFIX or p.name == ".DS_Store":
            continue
        files.append((rel, p))

    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for rel, p in files:
            name = "/".join((PREFIX, *rel.parts))
            zi = zipfile.ZipInfo(name, date_time=(2026, 11, 20, 8, 0, 0))
            zi.compress_type = zipfile.ZIP_DEFLATED
            zi.external_attr = (0o644 & 0xFFFF) << 16
            z.writestr(zi, p.read_bytes())

    digest = hashlib.sha256(out.read_bytes()).hexdigest()
    print(f"entries={len(files)}  bytes={out.stat().st_size}  sha256={digest}")
    with zipfile.ZipFile(out) as z:
        print("testzip:", z.testzip() or "OK")
        must = [
            "README.md", "BUILD.md", "INSTALL.md", "TROLLSTORE.md",
            "SuperLocator/project.yml", "SuperLocator/Tests/CoreTests.swift",
            "SuperLocator/Tests/golden.json", "tools/test_exe.py",
            "tools/verify_app.py", "tools/package_dist.py", "tools/make_golden.py",
            "ci/ios-ipa.yml", "companion/superlocator.py",
        ]
        for m in must:
            ok = f"{PREFIX}/{m}" in z.namelist()
            print(("  OK  " if ok else "  MISS") + f" {m}")
    return 0


if __name__ == "__main__":
    sys.exit(main())