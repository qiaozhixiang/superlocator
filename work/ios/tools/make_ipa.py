#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SuperLocator · IPA 打包与校验（Windows / macOS / Linux 都能跑）

用途：
  1) 把 Xcode 编出来的 SuperLocator.app 打成标准 .ipa（Payload/<name>.app + zip）
  2) 直接从 .xcarchive 里取 .app 打包
  3) 校验一个现成 .ipa：包名、版本、可执行文件、签名文件、Provisioning 是否在位

用法：
  python make_ipa.py --archive build/SuperLocator.xcarchive --out SuperLocator.ipa
  python make_ipa.py --app build/Release-iphoneos/SuperLocator.app --out SuperLocator.ipa
  python make_ipa.py --check SuperLocator.ipa
  python make_ipa.py --selftest           # 造一个 demo .app 验证打包器本身

说明：这里只做「装箱」，不做签名。安装前必须由 Xcode / Sideloadly / AltStore
     用你的 Apple ID 证书重签（见 ios/INSTALL.md）。
"""

from __future__ import annotations

import argparse
import hashlib
import os
import plistlib
import shutil
import stat
import sys
import tempfile
import zipfile
from pathlib import Path

APP_NAME = "SuperLocator"


# --------------------------------------------------------------------------- #
# 基本信息
# --------------------------------------------------------------------------- #
def read_info(app: Path) -> dict:
    info = app / "Info.plist"
    if not info.is_file():
        raise SystemExit(f"[x] 不是有效的 .app：缺少 {info}")
    with info.open("rb") as fh:
        return plistlib.load(fh)


def human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f}{unit}" if unit == "B" else f"{n/1:.1f}{unit}"
        n /= 1024.0
    return f"{n}B"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# --------------------------------------------------------------------------- #
# 打包
# --------------------------------------------------------------------------- #
def _zipinfo(rel: str, mode: int, is_dir: bool = False) -> zipfile.ZipInfo:
    zi = zipfile.ZipInfo(rel.replace(os.sep, "/"))
    zi.create_system = 3                      # unix，保留权限位
    zi.external_attr = (mode & 0xFFFF) << 16
    if is_dir:
        zi.external_attr |= 0x10              # 目录标志
        zi.compress_type = zipfile.ZIP_STORED
    else:
        zi.compress_type = zipfile.ZIP_DEFLATED
    zi.date_time = (2024, 1, 1, 0, 0, 0)
    return zi


def pack(app: Path, out: Path, quiet: bool = False) -> Path:
    app = app.resolve()
    info = read_info(app)
    if info.get("CFBundleExecutable") is None:
        raise SystemExit("[x] Info.plist 里没有 CFBundleExecutable")
    exe = app / info["CFBundleExecutable"]
    if not exe.is_file():
        raise SystemExit(f"[x] 可执行文件不存在：{exe}（先 xcodebuild build，别用空壳目录）")

    root_name = f"Payload/{app.name}"
    files = 0
    total = 0
    symlinks = 0

    with zipfile.ZipFile(out, "w", allowZip64=True) as zf:
        for dirpath, dirnames, filenames in os.walk(app, followlinks=False):
            cur = Path(dirpath)
            rel_dir = cur.relative_to(app)
            arc_dir = root_name if rel_dir == Path(".") else f"{root_name}/{rel_dir.as_posix()}"
            zf.writestr(_zipinfo(arc_dir + "/", 0o755, True), b"")

            for d in list(dirnames):
                p = cur / d
                if p.is_symlink():
                    arc = f"{arc_dir}/{d}"
                    target = os.readlink(p)
                    zf.writestr(_zipinfo(arc, 0o777), target.encode())
                    symlinks += 1
                    dirnames.remove(d)

            for f in filenames:
                p = cur / f
                arc = f"{arc_dir}/{f}"
                if p.is_symlink():
                    zf.writestr(_zipinfo(arc, 0o777), os.readlink(p).encode())
                    symlinks += 1
                    continue
                st = p.stat()
                mode = 0o755 if (st.st_mode & stat.S_IXUSR) else 0o644
                with p.open("rb") as fh:
                    zf.writestr(_zipinfo(arc, mode), fh.read())
                files += 1
                total += st.st_size

    if not quiet:
        print(f"[+] {app.name}: {files} 个文件（{human(total)}）+ {symlinks} 个符号链接")
        print(f"[+] 写出 {out}（{human(out.stat().st_size)}）")
    return out


def from_archive(archive: Path) -> Path:
    apps = sorted(archive.glob("Products/Applications/*.app"))
    if not apps:
        raise SystemExit(f"[x] {archive} 里没有 Products/Applications/*.app")
    return apps[0]


# --------------------------------------------------------------------------- #
# 校验
# --------------------------------------------------------------------------- #
def check(ipa: Path, allow_unsigned: bool = False) -> int:
    if not ipa.is_file():
        raise SystemExit(f"[x] 文件不存在：{ipa}")
    print(f"[i] {ipa.name}  {human(ipa.stat().st_size)}  sha256={sha256(ipa)}")
    problems = []
    with zipfile.ZipFile(ipa) as zf:
        bad = zf.testzip()
        if bad:
            problems.append(f"CRC 校验失败：{bad}")
        names = zf.namelist()
        apps = sorted({n.split("/")[1] for n in names
                       if n.startswith("Payload/") and n.count("/") >= 2 and n.endswith(".app/")})
        if len(apps) != 1:
            apps = sorted({n.split("/")[1] for n in names if n.startswith("Payload/")})
        print(f"[i] 条目 {len(names)} 个，Payload 下：{', '.join(apps) or '（空）'}")
        if not apps:
            problems.append("没有 Payload/<App>.app 结构，不是合法 IPA")
            apps = []
        for app in apps:
            base = f"Payload/{app}/"
            info_name = base + "Info.plist"
            if info_name not in names:
                problems.append(f"{app}: 缺 Info.plist")
                continue
            info = plistlib.loads(zf.read(info_name))
            bundle = info.get("CFBundleIdentifier", "?")
            ver = info.get("CFBundleShortVersionString", "?")
            build = info.get("CFBundleVersion", "?")
            minimum = info.get("MinimumOSVersion", "?")
            exe = info.get("CFBundleExecutable", "")
            print(f"[i] 包名 {bundle}  版本 {ver}（{build}）  最低系统 iOS {minimum}")
            print(f"[i] 显示名 {info.get('CFBundleDisplayName', info.get('CFBundleName', '?'))}")
            if base + exe not in names:
                problems.append(f"{app}: 可执行文件 {exe} 不在包里")
            signed = (base + exe) in names and (base + "_CodeSignature/CodeResources") in names
            prov = [n for n in names if n.startswith(base + "embedded.mobileprovision")]
            print(f"[i] 代码签名 {'在位' if signed else '缺失（未签名）'}  "
                  f"Provisioning {'在位' if prov else '缺失'}")
            if not signed:
                problems.append("未签名：需要 Xcode / Sideloadly / AltStore 用你的证书重签后才能装")
            if not prov:
                problems.append("没有 embedded.mobileprovision：真机安装前必须重签")
            for fw in sorted({n[len(base):].split("/")[0] for n in names
                              if n.startswith(base + "Frameworks/") and n.count("/") > 2}):
                mark = f"{base}Frameworks/{fw}/_CodeSignature/CodeResources"
                if mark not in names:
                    print(f"[!] 框架 {fw} 没有签名文件（重签时会一并处理）")
    if problems and allow_unsigned:
        problems = [x for x in problems if not (x.startswith("未签名") or x.startswith("没有 embedded.mobileprovision"))]
        if problems:
            print("[!] 除签名外还有问题")

    if problems:
        print("\n[!] 发现 %d 个问题：" % len(problems))
        for p in problems:
            print("    - " + p)
        return 1
    print("\n[+] 结构完整，可以交给签名工具")
    return 0


# --------------------------------------------------------------------------- #
# 自检（不需要 Xcode，验证打包器本身）
# --------------------------------------------------------------------------- #
def selftest() -> int:
    root = Path(__file__).resolve().parent.parent / "build" / "selftest"
    if root.exists():
        shutil.rmtree(root)
    app = root / f"{APP_NAME}.app"
    app.mkdir(parents=True)
    info = {
        "CFBundleIdentifier": "com.stv.locator",
        "CFBundleName": APP_NAME,
        "CFBundleDisplayName": "超级虚拟定位",
        "CFBundleExecutable": APP_NAME,
        "CFBundleShortVersionString": "1.0",
        "CFBundleVersion": "1",
        "MinimumOSVersion": "17.0",
        "CFBundlePackageType": "APPL",
        "UILaunchScreen": {},
    }
    with (app / "Info.plist").open("wb") as fh:
        plistlib.dump(info, fh)
    (app / APP_NAME).write_text("#!/bin/sh\necho demo\n", encoding="utf-8")
    os.chmod(app / APP_NAME, 0o755)
    (app / "Frameworks").mkdir()
    fw = app / "Frameworks" / "Demo.framework"
    fw.mkdir()
    (fw / "Demo").write_text("demo\n", encoding="utf-8")
    (fw / "Info.plist").write_text("<plist><dict/></plist>", encoding="utf-8")
    try:
        os.symlink("Demo", fw / "Current")
    except OSError:
        (fw / "Current").mkdir()          # Windows 无符号链接权限时退化（不影响打包器验证）

    out = root / f"{APP_NAME}-demo-unsigned.ipa"
    pack(app, out)
    print("-" * 60)
    return check(out)


def emit_tipa(ipa: Path, quiet: bool = False) -> Path:
    """TrollStore 认 .tipa 后缀（内容与 ipa 完全相同，只是让「文件」App 归给它）。"""
    tipa = ipa.with_suffix(".tipa")
    shutil.copyfile(ipa, tipa)
    if not quiet:
        print(f"[+] 同时写出 {tipa.name}（TrollStore 用，{human(tipa.stat().st_size)}）")
    return tipa


def main() -> int:
    ap = argparse.ArgumentParser(description="SuperLocator IPA 打包 / 校验")
    ap.add_argument("--app", type=Path, help=".app 目录")
    ap.add_argument("--archive", type=Path, help=".xcarchive")
    ap.add_argument("--out", type=Path, help="输出 .ipa 路径")
    ap.add_argument("--check", type=Path, metavar="IPA", help="校验现成 IPA")
    ap.add_argument("--tipa", action="store_true", help="额外产出一份 .tipa（TrollStore 直装）")
    ap.add_argument("--selftest", action="store_true", help="造 demo 验证打包器")
    ap.add_argument("--allow-unsigned", action="store_true", help="未签名/无描述文件不算失败（CI 出未签名 ipa 用）")
    args = ap.parse_args()

    if args.selftest:
        return selftest()
    if args.check:
        return check(args.check, args.allow_unsigned)
    if args.archive:
        app = from_archive(args.archive)
        out = args.out or Path(f"{app.stem}.ipa")
        pack(app, out)
        if args.tipa:
            emit_tipa(out)
        return check(out, args.allow_unsigned)
    if args.app:
        out = args.out or Path(f"{args.app.stem}.ipa")
        pack(args.app, out)
        if args.tipa:
            emit_tipa(out)
        return check(out, args.allow_unsigned)
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())