#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""inject_ddi.py -- 把 DDI 目录塞进 ipa/tipa 的 App 包内（ddi/<版本>/）。

DDI 必须在 App 内部，端上模式（Z2）才能自己挂载，否则会报
「包内没有 DDI（应存在 ddi/<版本>/BuildManifest.plist 与 Image.dmg）」。

用法：
  python tools/inject_ddi.py --ipa in.ipa --ddi ondevice/ddi/17.0 --ver 17.0 --out out.ipa
  python tools/inject_ddi.py --ipa SuperLocator.trollstore.tipa --ddi ondevice/ddi/17.0 --ver 17.0

注意：
- 会保留原有 ZipInfo 的权限位（可执行文件 0755），重新打包时不丢；
- 已存在同名条目会覆盖；
- 加点体积：personalized ≈17 MB，cryptex ≈17 MB。
"""

import argparse
import os
import sys
import zipfile


def payload_app(names):
    for n in names:
        if n.startswith("Payload/") and n.endswith(".app/"):
            return n
    # 有些 ipa 只写 Payload/X.app（无结尾斜杠的目录项），从文件名推断
    for n in names:
        if n.startswith("Payload/") and ".app/" in n:
            return n.split(".app/")[0] + ".app/"
    return None


def copy_info(src, dst):
    zi = zipfile.ZipInfo(dst, date_time=src.date_time)
    zi.compress_type = src.compress_type
    zi.external_attr = src.external_attr
    zi.create_system = src.create_system
    zi.internal_attr = src.internal_attr
    return zi


def main(argv=None):
    p = argparse.ArgumentParser(description="把 DDI 注入 ipa/tipa")
    p.add_argument("--ipa", required=True, help="输入 ipa 或 tipa")
    p.add_argument("--ddi", required=True, help="DDI 目录（含 BuildManifest.plist 与 Image.dmg）")
    p.add_argument("--ver", default="", help="包内目录名，例如 17.0（默认取 DDI 目录名）")
    p.add_argument("--out", default="", help="输出路径（默认覆盖输入文件）")
    args = p.parse_args(argv)

    if not os.path.isdir(args.ddi):
        print(f"[!] DDI 目录不存在：{args.ddi}", file=sys.stderr)
        return 2
    for need in ("BuildManifest.plist", "Image.dmg"):
        if not os.path.exists(os.path.join(args.ddi, need)):
            print(f"[!] DDI 目录缺 {need}", file=sys.stderr)
            return 2

    ver = args.ver or os.path.basename(os.path.normpath(args.ddi))
    out = args.out or args.ipa
    tmp = out + ".tmp"

    with zipfile.ZipFile(args.ipa) as zin:
        app = payload_app(zin.namelist())
        if not app:
            print("[!] 这不像一个 ipa：找不到 Payload/*.app/", file=sys.stderr)
            return 3
        names = set(zin.namelist())
        added = 0
        with zipfile.ZipFile(tmp, "w") as zout:
            for item in zin.infolist():
                zout.writestr(copy_info(item, item.filename), zin.read(item.filename))
            for fn in sorted(os.listdir(args.ddi)):
                src_path = os.path.join(args.ddi, fn)
                if not os.path.isfile(src_path):
                    continue
                dst = f"{app}ddi/{ver}/{fn}"
                if dst in names:
                    continue
                zi = zipfile.ZipInfo(dst, date_time=(2024, 1, 1, 0, 0, 0))
                zi.compress_type = zipfile.ZIP_DEFLATED
                zi.external_attr = 0o644 << 16
                zi.create_system = 3
                with open(src_path, "rb") as f:
                    zout.writestr(zi, f.read())
                added += 1
    os.replace(tmp, out)

    size = os.path.getsize(out)
    with zipfile.ZipFile(out) as z:
        bad = z.testzip()
        ddi_entries = [n for n in z.namelist() if "/ddi/" in n]
    print(f"[OK] 注入 {added} 个 DDI 文件到 {os.path.basename(out)}（{size:,d} 字节）")
    print(f"     包内 ddi 条目：{len(ddi_entries)}")
    print(f"     zip 完整性：{'坏条目 ' + str(bad) if bad else '通过'}")
    for n in ddi_entries[:6]:
        print(f"       {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())