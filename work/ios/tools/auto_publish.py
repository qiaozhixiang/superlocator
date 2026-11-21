# -*- coding: utf-8 -*-
"""等授权 → 建仓 → 推 → 盯 CI → 把 ipa 拉回 dist。

用法（后台跑，授权后自动完成）：
    python tools/auto_publish.py --repo qiaozhixiang/superlocator --timeout 1500
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOKEN_FILE = ROOT / ".publish" / "gh_token.txt"


def wait_token(limit: float = 1200.0) -> str:
    t0 = time.time()
    while time.time() - t0 < limit:
        if TOKEN_FILE.is_file():
            tok = TOKEN_FILE.read_text(encoding="utf-8").strip()
            if len(tok) > 20:
                return tok
        time.sleep(3)
    return ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default="qiaozhixiang/superlocator")
    ap.add_argument("--timeout", type=int, default=1500)
    ap.add_argument("--wait-token", type=int, default=1200)
    ap.add_argument("--download", default="dist")
    args = ap.parse_args()

    print(f"[..] 等授权（最多 {args.wait_token}s）：{TOKEN_FILE}", flush=True)
    tok = wait_token(args.wait_token)
    if not tok:
        print("[x] 没等到授权 token，设备码大概过期了；重跑 tools/gh_device.py", flush=True)
        return 2
    print(f"[OK] 拿到 token（{len(tok)} 字符），开始建仓/推送", flush=True)

    cmd = [sys.executable, str(ROOT / "tools" / "publish.py"),
           "--repo", args.repo,
           "--token", tok,
           "--wait",
           "--timeout", str(args.timeout),
           "--download", str(ROOT / args.download)]
    print("[..] " + " ".join(cmd[:3] + ["..."]), flush=True)
    rc = subprocess.call(cmd, cwd=str(ROOT))
    print(f"[{'OK' if rc == 0 else 'x'}] publish.py 退出码 {rc}", flush=True)
    return rc


if __name__ == "__main__":
    sys.exit(main())