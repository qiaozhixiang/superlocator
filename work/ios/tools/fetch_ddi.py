#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fetch_ddi.py -- 不需要 Mac，直接把 iOS 开发者磁盘镜像（DDI）下到本地。

DDI 是 `com.apple.dt.simulatelocation` 服务的载体。它不在系统里，需要单独准备。
这个脚本从社区镜像仓库（doronz88/DeveloperDiskImage，pymobiledevice3 官方也用它）
拉取对应变体的三个（或五个）文件，校验大小与 sha256，落到 ddi/<版本>/ 里。

用法：
  python tools/fetch_ddi.py --ios 17.0                     # 默认 personalized（iOS 14–17.3）
  python tools/fetch_ddi.py --ios 18.0 --variant cryptex   # iOS 18+ / Xcode 16 的 cryptex 形态
  python tools/fetch_ddi.py --ios 17.0 --list              # 只打印文件清单与大小
  python tools/fetch_ddi.py --ios 17.0 --mirror https://ghfast.top/  # 直连 GitHub 慢时

产物目录结构（直接塞进 App 包）：
  SuperLocator.app/ddi/17.0/BuildManifest.plist
  SuperLocator.app/ddi/17.0/Image.dmg
  SuperLocator.app/ddi/17.0/Image.dmg.trustcache
"""

import argparse
import hashlib
import json
import os
import sys
import urllib.request

REPO = "doronz88/DeveloperDiskImage"
API = f"https://api.github.com/repos/{REPO}/contents"
RAW = f"https://raw.githubusercontent.com/{REPO}/main"

VARIANTS = {
    "personalized": {
        "dir": "PersonalizedImages/Xcode_iOS_DDI_Personalized",
        "files": ["BuildManifest.plist", "Image.dmg", "Image.dmg.trustcache"],
        "ios": "iOS 14 – 17.3（Xcode 15 及更早）",
    },
    "cryptex": {
        "dir": "PersonalizedImages/Xcode_iOS_DDI_Cryptex",
        "files": [
            "BuildManifest.plist",
            "Image.dmg",
            "Image.dmg.trustcache",
            "Image.dmg.cryptex_info",
            "Image.dmg.root_hash",
        ],
        "ios": "iOS 17.4 – 18.x（Xcode 16+，DDI 变成 cryptex）",
    },
}

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_OUT = os.path.join(ROOT, "ondevice", "ddi")


def api_listing(subdir):
    url = f"{API}/{subdir}?ref=main"
    req = urllib.request.Request(url, headers={"User-Agent": "stv-fetch-ddi"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.load(r)
    return {item["name"]: item for item in data if item.get("type") == "file"}


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download(url, dest, expect_size=None):
    tmp = dest + ".part"
    req = urllib.request.Request(url, headers={"User-Agent": "stv-fetch-ddi"})
    with urllib.request.urlopen(req, timeout=180) as r, open(tmp, "wb") as f:
        total = 0
        while True:
            chunk = r.read(1 << 16)
            if not chunk:
                break
            f.write(chunk)
            total += len(chunk)
    if expect_size is not None and total != expect_size:
        os.unlink(tmp)
        raise RuntimeError(f"大小不符：期望 {expect_size} 实得 {total}（{url}）")
    os.replace(tmp, dest)
    return total


def main(argv=None):
    p = argparse.ArgumentParser(description="下载 iOS DDI（无需 Mac）")
    p.add_argument("--ios", default="17.0", help="目标系统版本，例如 17.0 / 18.0（默认 17.0）")
    p.add_argument("--variant", choices=sorted(VARIANTS), default="personalized")
    p.add_argument("--out", default=DEFAULT_OUT, help="输出根目录（默认 work/ios/ondevice/ddi）")
    p.add_argument("--mirror", default="", help="GitHub 加速前缀，例如 https://ghfast.top/")
    p.add_argument("--list", action="store_true", help="只列出远端文件与大小，不下载")
    p.add_argument("--force", action="store_true", help="已存在也重下")
    args = p.parse_args(argv)

    v = VARIANTS[args.variant]
    print(f"变体：{args.variant}（{v['ios']}）")
    print(f"远端：{REPO}/{v['dir']}")

    try:
        listing = api_listing(v["dir"])
    except Exception as e:
        print(f"[!] 取文件清单失败：{e}\n    可加 --mirror https://ghfast.top/ 再试")
        return 2

    missing = [n for n in v["files"] if n not in listing]
    if missing:
        print(f"[!] 远端缺文件：{missing}")
        return 3

    total = sum(listing[n]["size"] for n in v["files"])
    for n in v["files"]:
        print(f"  - {n:28s} {listing[n]['size']:>12,d} 字节")
    print(f"  合计 {total:,d} 字节（约 {total/1048576:.1f} MB）")

    if args.list:
        return 0

    out = os.path.join(args.out, args.ios)
    os.makedirs(out, exist_ok=True)
    index = {"variant": args.variant, "ios": args.ios, "repo": REPO, "dir": v["dir"], "files": {}}

    ok = True
    for n in v["files"]:
        dest = os.path.join(out, n)
        size = listing[n]["size"]
        if os.path.exists(dest) and os.path.getsize(dest) == size and not args.force:
            print(f"[=] {n} 已存在且大小一致，跳过")
        else:
            url = f"{RAW}/{v['dir']}/{n}"
            if args.mirror:
                url = args.mirror.rstrip("/") + "/" + url
            print(f"[↓] {n} …")
            try:
                download(url, dest, size)
            except Exception as e:
                print(f"[!] {n} 下载失败：{e}")
                ok = False
                continue
        index["files"][n] = {"size": size, "sha256": sha256_of(dest)}

    with open(os.path.join(out, "ddi_index.json"), "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)

    print()
    for n, meta in index["files"].items():
        print(f"  {n:28s} {meta['size']:>12,d}  sha256 {meta['sha256']}")
    print(f"\n输出目录：{out}")
    print("把这个目录整体放进 App 包：SuperLocator.app/ddi/<系统版本>/（DDIMounter 会自动找）")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())