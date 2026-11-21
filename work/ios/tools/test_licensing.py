# -*- coding: utf-8 -*-
"""iOS 侧授权中心自检：TCP + HTTP 两道门、激活/吊销/删除即时生效。"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
IOS = HERE.parent
COMPANION = IOS / "companion"
TMP = IOS / "build" / "tmp" / "licensetest"
PORT = 47970
HTTP = 47971
DEV = "iphone-15-pro-test"
DEV2 = "ipad-mini-test"
NL = chr(10)


def run_cli(*argv: str) -> str:
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["TEMP"] = env["TMP"] = env["TMPDIR"] = str(IOS / "build" / "tmp")
    r = subprocess.run([sys.executable, str(COMPANION / "superlocator.py"), "license",
                        "--dir", str(TMP / "license"), *argv],
                       capture_output=True, text=True, env=env, encoding="utf-8")
    if r.returncode != 0:
        raise SystemExit("license " + " ".join(argv) + " 失败：" + r.stdout + r.stderr)
    return r.stdout


def tcp(msgs, device=DEV):
    """服务器连上先推一条 hello 事件；回执与事件共用一条流，必须按 cmd 匹配着读。"""
    out = []
    with socket.create_connection(("127.0.0.1", PORT), timeout=8) as s:
        f = s.makefile("rwb")
        f.write((json.dumps({"cmd": "ping"}) + NL).encode())
        f.flush()
        while True:
            line = f.readline()
            if not line:
                raise SystemExit("连接被关闭")
            if json.loads(line.decode()).get("cmd") == "ping":
                break
        for m in msgs:
            m.setdefault("device", device)
            f.write((json.dumps(m) + NL).encode())
            f.flush()
            while True:
                line = f.readline()
                if not line:
                    raise SystemExit("无回执：" + str(m.get("cmd")))
                obj = json.loads(line.decode())
                if obj.get("cmd") == m["cmd"]:
                    out.append(obj)
                    break
    return out


def http_json(path, body=None):
    url = "http://127.0.0.1:" + str(HTTP) + path
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=8) as r:
        return json.loads(r.read().decode())


def start_server():
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["TEMP"] = env["TMP"] = env["TMPDIR"] = str(IOS / "build" / "tmp")
    return subprocess.Popen([sys.executable, str(COMPANION / "superlocator.py"), "serve",
                             "--engine", "dry", "--port", str(PORT), "--http-port", str(HTTP),
                             "--license-dir", str(TMP / "license")],
                            env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)


def main() -> int:
    TMP.mkdir(parents=True, exist_ok=True)
    lic = TMP / "license"
    for name in ("state.json", "ledger.json"):
        p = lic / name
        if p.exists():
            p.unlink()
    run_cli("init")
    code = run_cli("keygen", "-n", "1", "--note", "自检").split()[1]
    print("生成的激活码：" + code)

    srv = start_server()
    ok = True
    try:
        for _ in range(60):
            try:
                socket.create_connection(("127.0.0.1", PORT), timeout=0.3).close()
                break
            except OSError:
                time.sleep(0.25)

        def check(name, want, got, extra=""):
            nonlocal ok
            print(("PASS " if want == got else "FAIL ") + name + ("  " + extra if extra else ""))
            ok = ok and (want == got)

        r = tcp([{"cmd": "ping"}])[0]
        check("ping 可用", True, r.get("ok"), str(r.get("version", "")))

        r = tcp([{"cmd": "hello"}])[0]
        lic_state = r.get("license") or {}
        check("hello 带授权状态（未激活）", False, lic_state.get("active"),
              json.dumps(lic_state, ensure_ascii=False))

        r = tcp([{"cmd": "set", "lat": 36.71, "lon": 117.02}])[0]
        check("未激活时 set 被拦", True, r.get("needLicense"), str(r.get("error", "")))

        r = tcp([{"cmd": "play", "payload": {"kind": "track", "points": [[0, 36.71, 117.02]]}}])[0]
        check("未激活时 play 被拦", True, r.get("needLicense"))

        r = tcp([{"cmd": "license_activate", "code": "01EQ4-B8V3Z-DXV3K-HR6XZ"}])[0]
        check("错码被拒", False, r.get("ok"), str(r.get("message", "")))

        r = tcp([{"cmd": "license_activate", "code": code.lower()}])[0]
        check("正确码激活成功（大小写不敏感）", True, r.get("ok"), str(r.get("message", "")))

        r = tcp([{"cmd": "license_status"}])[0]
        check("状态变为已激活", True, r.get("active"), "serial=" + str(r.get("serial")))

        r = tcp([{"cmd": "set", "lat": 36.71, "lon": 117.02}])[0]
        check("激活后 set 放行", True, r.get("ok"))

        st = http_json("/api/license/status?device=" + DEV2)
        check("HTTP 状态（另一台设备未激活）", False, st.get("active"))
        act = http_json("/api/license/activate", {"code": code, "device": DEV2})
        check("HTTP 激活成功", True, act.get("ok"), str(act.get("message", "")))
        bad = http_json("/api/cmd", {"cmd": "set", "lat": 1, "lon": 1})
        check("HTTP 无 device 的 set 被拦", True, bad.get("needLicense"))

        page = urllib.request.urlopen("http://127.0.0.1:" + str(HTTP) + "/", timeout=8).read().decode()
        check("网页版含激活码输入框", True, "liccode" in page and "licActivate" in page)
        check("网页版命令带 device 字段", True, "device:DEV" in page)

        serial = int(r.get("serial") or 1)
        run_cli("revoke", "--serial", str(serial))
        r = tcp([{"cmd": "license_status"}])[0]
        check("吊销后立刻变未激活", False, r.get("active"))
        r = tcp([{"cmd": "set", "lat": 1, "lon": 1}])[0]
        check("吊销后 set 再次被拦", True, r.get("needLicense"))

        run_cli("unrevoke", "--serial", str(serial))
        r = tcp([{"cmd": "license_status"}])[0]
        check("恢复吊销后立刻可用", True, r.get("active"))

        run_cli("delete", "--serial", str(serial))
        r = tcp([{"cmd": "license_status"}])[0]
        check("删除码后立刻失效", False, r.get("active"))
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=5)
        except subprocess.TimeoutExpired:
            srv.kill()

    print(NL + ("全部通过" if ok else "有失败"))
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())