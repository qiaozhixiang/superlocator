# -*- coding: utf-8 -*-
"""服务器模式（relay）自检：主机 serve --engine relay + 本机 agent + 一次 set 往返。"""
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable
HOST_PORT, RELAY_PORT, TOKEN = 47971, 47970, "sekret-test"


def wait_port(port, timeout=12.0):
    end = time.time() + timeout
    while time.time() < end:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                return True
        except OSError:
            time.sleep(0.2)
    return False


def cmd(sock_file, payload, want, timeout_steps=200):
    sock_file.write((json.dumps(payload) + "\n").encode())
    sock_file.flush()
    for _ in range(timeout_steps):
        line = sock_file.readline()
        if not line:
            raise RuntimeError("连接断了")
        obj = json.loads(line.decode("utf-8"))
        if obj.get("cmd") == want:
            return obj
    raise RuntimeError(f"没等到 {want} 的回执")


def main():
    env = dict(os.environ)
    tmp = ROOT / "build" / "tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    env["TEMP"] = env["TMP"] = env["TMPDIR"] = str(tmp)
    env["PYTHONIOENCODING"] = "utf-8"

    host = subprocess.Popen(
        [PY, "-u", str(ROOT / "companion" / "superlocator.py"), "serve",
         "--engine", "relay", "--relay-port", str(RELAY_PORT), "--relay-token", TOKEN,
         "--port", str(HOST_PORT), "--http-port", "0", "--no-license", "--quiet",
         "--license-dir", str(tmp / "lic")],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env)
    ok = True
    try:
        assert wait_port(HOST_PORT), "主机没起来"
        print("PASS 主机监听", HOST_PORT)

        # 1) 错 token 的 agent 必须被拒
        bad = socket.create_connection(("127.0.0.1", RELAY_PORT), timeout=5)
        bf = bad.makefile("rwb")
        bf.write((json.dumps({"op": "hello", "token": "wrong"}) + "\n").encode())
        bf.flush()
        rej = json.loads(bf.readline().decode("utf-8"))
        assert rej.get("ok") is False, "错 token 竟然通过了"
        bad.close()
        print("PASS 错 token 被拒：", rej.get("error"))

        # 2) 正常 agent
        agent = subprocess.Popen(
            [PY, "-u", str(ROOT / "companion" / "superlocator.py"), "agent",
             "--host", "127.0.0.1", "--port", str(RELAY_PORT), "--token", TOKEN,
             "--engine", "dry"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env)
        time.sleep(1.5)

        # 3) 客户端 set 必须成功，并且坐标真的到 agent 的 dry 引擎
        s = socket.create_connection(("127.0.0.1", HOST_PORT), timeout=5)
        f = s.makefile("rwb")
        cmd(f, {"cmd": "ping"}, "ping")
        res = cmd(f, {"cmd": "set", "lat": 36.123456, "lon": 117.654321}, "set")
        assert res.get("ok") is True, res
        print("PASS set 往返：", res.get("lat"), res.get("lon"))
        st = cmd(f, {"cmd": "status"}, "status")
        assert st.get("ok") is True
        print("PASS status 可用：", st.get("running"))
        s.close()

        time.sleep(0.5)
        agent.terminate()
        try:
            out = agent.communicate(timeout=5)[0].decode("utf-8", "replace")
        except subprocess.TimeoutExpired:
            agent.kill()
            out = ""
        assert "36.123456" in out, f"agent 没收到坐标：{out[-400:]}"
        print("PASS agent 侧收到坐标（dry 打印 36.123456）")
        print("RESULT: relay 全部通过")
    except AssertionError as exc:
        ok = False
        print("FAIL:", exc)
    finally:
        host.terminate()
        try:
            log = host.communicate(timeout=6)[0].decode("utf-8", "replace")
        except subprocess.TimeoutExpired:
            host.kill()
            log = ""
        if not ok:
            print("---- 主机日志 ----")
            print(log[-2000:])
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())