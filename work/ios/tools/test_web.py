# -*- coding: utf-8 -*-
"""网页版自检：页面 JS 语法 + HTTP 接口实测（不需要 iPhone、不需要引擎）。"""
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "companion"))

from webapp_page import PAGE  # noqa: E402

TMP = ROOT / "build" / "tmp"
TMP.mkdir(parents=True, exist_ok=True)
for k in ("TEMP", "TMP", "TMPDIR"):
    os.environ[k] = str(TMP)


def js_check() -> bool:
    body = re.search(r"<script>(.*)</script>", PAGE, re.S)
    if not body:
        print("FAIL 没找到 <script>")
        return False
    src = TMP / "webapp_check.js"
    src.write_text(body.group(1), encoding="utf-8")
    exe = ROOT / "build" / "exe" / "superlocator.exe"
    try:
        r = subprocess.run(["node", "--check", str(src)], capture_output=True, text=True, timeout=60)
    except FileNotFoundError:
        print("SKIP 没有 node，跳过 JS 语法检查")
        return True
    ok = r.returncode == 0
    print(("PASS" if ok else "FAIL") + " JS 语法 " + (r.stderr.strip()[:400] if not ok else f"({len(body.group(1))} 字符)"))
    return ok


def post(base, obj):
    req = urllib.request.Request(base + "/api/cmd", data=json.dumps(obj).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return {"ok": False, "error": f"HTTP {e.code}"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}


def http_check(use_exe: bool = False) -> bool:
    port, web = 47900, 47901
    exe = ROOT / "build" / "exe" / "superlocator.exe"
    if use_exe:
        if not exe.exists():
            print("FAIL 找不到 build/exe/superlocator.exe，先编")
            return False
        cmd = [str(exe)]
    else:
        cmd = [sys.executable, str(ROOT / "companion" / "superlocator.py")]
    cmd += ["serve", "--engine", "dry", "--no-license", "--port", str(port), "--http-port", str(web), "--quiet"]
    proc = subprocess.Popen(cmd, cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace")
    ok = True
    try:
        base = f"http://127.0.0.1:{web}"
        html = ""
        for _ in range(40):
            time.sleep(0.35)
            try:
                with urllib.request.urlopen(base + "/", timeout=3) as r:
                    html = r.read().decode("utf-8")
                break
            except Exception:  # noqa: BLE001
                continue
        checks = [
            ("页面 200 且有标题", "超级虚拟定位 · 网页版" in html),
            ("页面含地图容器", 'id="map"' in html),
            ("页面含命令通道", "/api/cmd" in html),
            ("ping", post(base, {"cmd": "ping"}).get("ok") is True),
            ("set", post(base, {"cmd": "set", "lat": 36.71021, "lon": 117.02155}).get("ok") is True),
            ("jitter", post(base, {"cmd": "jitter", "radius": 20, "bias": 0.6, "bearing": 90}).get("ok") is True),
            ("play(track)", post(base, {"cmd": "play", "payload": {
                "kind": "track", "name": "t", "intervalMs": 200,
                "points": [[0, 36.71, 117.02], [2000, 36.7105, 117.0205], [4000, 36.7110, 117.0210]],
                "speed": 2.0, "radius": 15, "bias": 0.5}}).get("ok") is True),
        ]
        time.sleep(1.2)
        st = post(base, {"cmd": "status"})
        checks.append(("status running", st.get("ok") is True and st.get("running") is True))
        checks.append(("status 有帧/进度", isinstance(st.get("pushes"), (int, float)) and st["pushes"] >= 1))
        checks.append(("stop", post(base, {"cmd": "stop"}).get("ok") is True))
        checks.append(("非法命令被拒", post(base, {"cmd": "nope"}).get("ok") is False))
        for name, passed in checks:
            print(("PASS " if passed else "FAIL ") + name)
            ok = ok and passed
        print(f"  推送帧数={st.get('pushes')} 进度={st.get('progress')} 抖动={st.get('jitter')}")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=6)
        except subprocess.TimeoutExpired:
            proc.kill()
    return ok


if __name__ == "__main__":
    use_exe = "--exe" in sys.argv
    print("被测对象：" + ("dist/exe（编译产物）" if use_exe else "python 源码"))
    a = js_check()
    b = http_check(use_exe)
    print("WEB 自检：" + ("全部通过" if a and b else "有失败"))
    sys.exit(0 if a and b else 2)