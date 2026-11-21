# -*- coding: utf-8 -*-
"""把未签名 ipa 变成「带特权 entitlements 的 tipa」——TrollStore 端上直装用。

为什么需要：iOS 上想在本机直接调用 `com.apple.dt.simulatelocation`，进程必须有
`com.apple.private.dvt.simulatelocation` 等 entitlement；普通签名给不了，
但 TrollStore 用 CoreTrust 漏洞安装时会原样保留二进制里的 entitlements。
所以：先用 ad-hoc / ldid 把 entitlements 塞进去 → 再用 TrollStore 装 → App 自己就能改定位。

用法：
  macOS： python3 tools/make_tipa.py --ipa in.ipa --out SuperLocator.tipa
  Linux： python3 tools/make_tipa.py --ipa in.ipa --out SuperLocator.tipa --ldid ./ldid
  干跑：  python3 tools/make_tipa.py --ipa in.ipa --out t.tipa --no-sign
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ENT = ROOT / "ondevice" / "entitlements.plist"
LDID_URL = "https://github.com/ProcursusTeam/ldid/releases/latest/download/ldid_linux_x86_64"


def run(cmd: list[str], **kw) -> int:
    print("  $ " + " ".join(cmd))
    return subprocess.call(cmd, **kw)


def find_signer(ldid: str | None) -> tuple[str, str]:
    """返回 (工具, 路径)：优先 codesign（macOS 自带），否则 ldid。"""
    if ldid:
        return "ldid", ldid
    if sys.platform == "darwin" and shutil.which("codesign"):
        return "codesign", shutil.which("codesign") or "codesign"
    for name in ("ldid", "ldid2"):
        p = shutil.which(name)
        if p:
            return "ldid", p
    return "", ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ipa", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--entitlements", default=str(DEFAULT_ENT))
    ap.add_argument("--ldid", default=None)
    ap.add_argument("--no-sign", action="store_true", help="只重打包，不签名（自测用）")
    args = ap.parse_args()

    ipa = Path(args.ipa)
    out = Path(args.out)
    ent = Path(args.entitlements)
    if not ipa.is_file():
        print(f"[x] 找不到 ipa：{ipa}")
        return 2
    if not ent.is_file():
        print(f"[x] 找不到 entitlements：{ent}")
        return 2

    tool, path = (("", "") if args.no_sign else find_signer(args.ldid))
    if not args.no_sign and not tool:
        print("[x] 没找到签名工具：macOS 需要 codesign（自带），Linux 需要 ldid")
        print(f"    下载 ldid：curl -L {LDID_URL} -o ldid && chmod +x ldid")
        return 3

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        with zipfile.ZipFile(ipa) as z:
            z.extractall(tmp)
        apps = list((tmp / "Payload").glob("*.app"))
        if not apps:
            print("[x] ipa 里没有 Payload/*.app")
            return 4
        app = apps[0]
        exe = app / app.stem
        if not exe.is_file():
            cands = [p for p in app.iterdir() if p.is_file() and os.access(p, os.X_OK)]
            if not cands:
                print("[x] 找不到可执行文件")
                return 5
            exe = cands[0]
        print(f"[..] App={app.name} exe={exe.name}")

        if tool == "codesign":
            rc = run([path, "--force", "--sign", "-", "--entitlements", str(ent),
                      "--timestamp=none", str(app)])
        elif tool == "ldid":
            rc = run([path, f"-S{ent}", str(exe)])
        else:
            rc = 0
        if rc != 0:
            print(f"[x] 签名失败（{tool} 退出码 {rc}）")
            return 6

        # 把 entitlements 记在包里，装完能核对
        shutil.copy2(ent, app / "SuperLocatorEntitlements.plist")

        if out.exists():
            out.unlink()
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
            for p in sorted(tmp.rglob("*")):
                rel = p.relative_to(tmp).as_posix()
                info = zipfile.ZipInfo(rel)
                info.create_system = 3
                if p.is_dir():
                    info.external_attr = (0o40755 << 16) | 0x10
                    z.writestr(info, b"")
                else:
                    info.external_attr = (0o100755 if os.access(p, os.X_OK) else 0o100644) << 16
                    z.writestr(info, p.read_bytes())

    print(f"[OK] {out}  {out.stat().st_size:,} 字节")
    print("     装法：传到手机 → 用 TrollStore 打开（不是「文件」App）→ Install")
    return 0


if __name__ == "__main__":
    sys.exit(main())