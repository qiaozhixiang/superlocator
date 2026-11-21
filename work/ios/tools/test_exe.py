#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""伴侣程序（含 PyInstaller 打出的 superlocator.exe）功能自测

跑法：
  python work/ios/tools/test_exe.py                    # 自动找 exe，找不到就用 python 跑源码
  python work/ios/tools/test_exe.py --exe build/exe/superlocator.exe

覆盖：
  1) --help 与子命令是否齐全
  2) serve 起得来、握手事件正确
  3) ping / set / jitter / play(track) / status / stop 全命令往返
  4) 播放时坐标真的在动（progress 递增、坐标在包络内）
  5) 抖动上界 = 1.5R，且 bias=0.9 / bearing=90° 时整体偏东
  6) `play --engine dry` 命令行输出坐标流
"""

from __future__ import annotations

import argparse
import json
import math
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COMPANION = ROOT / "companion"
DEFAULT_EXE = ROOT / "build" / "exe" / "superlocator.exe"

PASS: list[str] = []
FAIL: list[str] = []


def ok(name: str, detail: str = "") -> None:
    PASS.append(f"{name} {detail}".strip())
    print(f"  [PASS] {name} {detail}")


def bad(name: str, detail: str = "") -> None:
    FAIL.append(f"{name} {detail}".strip())
    print(f"  [FAIL] {name} {detail}")


def launch(engine: str, port: int) -> subprocess.Popen:
    if EXE and EXE.is_file():
        cmd = [str(EXE)]
    else:
        cmd = [sys.executable, str(COMPANION / "superlocator.py")]
    return subprocess.Popen(
        cmd + ["serve", "--engine", engine, "--no-license", "--port", str(port)],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        encoding="utf-8", errors="replace", bufsize=1,
    )


def wait_port(port: int, timeout: float = 25.0) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout:
        with socket.socket() as s:
            s.settimeout(0.4)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return True
        time.sleep(0.2)
    return False


class Link:
    def __init__(self, port: int):
        self.sock = socket.create_connection(("127.0.0.1", port), timeout=5)
        self.f = self.sock.makefile("rwb")

    def send(self, **obj) -> None:
        self.f.write((json.dumps(obj, ensure_ascii=False) + "\n").encode())
        self.f.flush()

    def recv(self) -> dict:
        line = self.f.readline()
        if not line:
            raise RuntimeError("连接被关闭")
        return json.loads(line.decode())

    def reply(self, cmd: str, timeout: float = 9.0) -> dict:
        """读命令回执；播放期间同一条 socket 会插播 position 事件，跳过它们。"""
        t0 = time.time()
        while time.time() - t0 < timeout:
            obj = self.recv()
            if obj.get("cmd") == cmd:
                return obj
        raise RuntimeError(f"等不到 {cmd} 回执")

    def wait_event(self, event: str, timeout: float = 6.0) -> dict:
        t0 = time.time()
        while time.time() - t0 < timeout:
            obj = self.recv()
            if obj.get("event") == event:
                return obj
        raise RuntimeError(f"等不到 {event} 事件")

    def close(self) -> None:
        try:
            self.f.close()
            self.sock.close()
        except Exception:
            pass


def metres(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371008.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def test_cli() -> None:
    print("[1] 命令行接口")
    cmd = [str(EXE)] if EXE and EXE.is_file() else [sys.executable, str(COMPANION / "superlocator.py")]
    r = subprocess.run(cmd + ["--help"], capture_output=True, text=True, timeout=90,
                       encoding="utf-8", errors="replace")
    text = (r.stdout or "") + (r.stderr or "")
    for sub in ("serve", "set", "play", "clear", "list"):
        (ok if sub in text else bad)(f"子命令 {sub}", "存在" if sub in text else "缺失")
    ok("exit code", str(r.returncode))


def test_serve_track(port: int) -> None:
    print("[2] serve + track 播放")
    proc = launch("dry", port)
    try:
        if not wait_port(port):
            bad("serve 启动")
            return
        ok("serve 启动", f"port {port}")

        link = Link(port)
        hello = link.wait_event("hello")
        ok("握手", f"version={hello.get('version')}")

        link.send(cmd="ping")
        r = link.recv()
        ok("ping", str(r.get("ok")))

        lat0, lon0 = 36.710210, 117.021550
        link.send(cmd="set", lat=lat0, lon=lon0)
        r = link.reply("set")
        (ok if r.get("ok") else bad)("set", f"{r.get('lat')},{r.get('lon')}")

        link.send(cmd="jitter", radius=0.0, bias=0.0, bearing=None)
        r = link.reply("jitter")
        (ok if r.get("ok") else bad)("jitter 关闭", r.get("desc", "")[:40])

        track = json.loads((COMPANION / "samples" / "track_campus.json").read_text(encoding="utf-8"))
        payload = dict(track)
        payload.update({"kind": "track", "speed": 6.0, "loop": True, "radius": 0.0})
        link.send(cmd="play", payload=payload)
        r = link.reply("play")
        (ok if r.get("ok") else bad)("play(track)", f"kind={r.get('kind')}")

        pts = []
        t0 = time.time()
        while len(pts) < 15 and time.time() - t0 < 12:
            obj = link.recv()
            if obj.get("event") == "position":
                pts.append(obj)
        (ok if len(pts) >= 15 else bad)("坐标帧", f"{len(pts)} 帧")

        if len(pts) >= 3:
            moved = metres(pts[0]["lat"], pts[0]["lon"], pts[-1]["lat"], pts[-1]["lon"])
            (ok if moved > 0.5 else bad)("位置在移动", f"首末位移 {moved:.2f} m")
            p0, p1 = pts[0].get("progress", 0), pts[-1].get("progress", 0)
            (ok if p1 != p0 else bad)("progress 递增", f"{p0:.3f} -> {p1:.3f}")

        link.send(cmd="stop")
        r = link.reply("stop")
        (ok if r.get("ok") else bad)("stop", str(r.get("cmd")))
        link.close()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            proc.kill()


def test_jitter(port: int) -> None:
    print("[3] 抖动：上界与偏向方向")
    proc = launch("dry", port)
    try:
        if not wait_port(port):
            bad("serve 启动(jitter)")
            return
        link = Link(port)
        link.wait_event("hello")
        lat0, lon0 = 36.710210, 117.021550
        link.send(cmd="set", lat=lat0, lon=lon0)
        link.reply("set")
        radius, bias, bearing = 50.0, 0.9, 90.0
        link.send(cmd="jitter", radius=radius, bias=bias, bearing=bearing)
        r = link.reply("jitter")
        (ok if r.get("ok") else bad)("jitter 设置", str(r.get("desc"))[:60])

        track = json.loads((COMPANION / "samples" / "track_campus.json").read_text(encoding="utf-8"))
        payload = dict(track)
        payload.update({"kind": "track", "speed": 1.0, "loop": True,
                        "radius": radius, "bias": bias, "bearing": bearing})
        link.send(cmd="play", payload=payload)
        link.reply("play")

        offsets = []
        t0 = time.time()
        while len(offsets) < 40 and time.time() - t0 < 25:
            obj = link.recv()
            if obj.get("event") == "position":
                base_lat, base_lon = obj.get("baseLat"), obj.get("baseLon")
                if base_lat is None:
                    continue
                d = metres(base_lat, base_lon, obj["lat"], obj["lon"])
                offsets.append((d, obj["lon"] - base_lon))
        (ok if len(offsets) >= 20 else bad)("抖动采样", f"{len(offsets)} 帧")
        if offsets:
            mx = max(o[0] for o in offsets)
            (ok if mx <= radius * 1.5 + 1.0 else bad)("上界 ≤ 1.5R", f"max {mx:.2f} m / 上限 {radius*1.5:.0f} m")
            east = sum(1 for o in offsets if o[1] > 0)
            (ok if east / len(offsets) >= 0.6 else bad)(
                "偏东一致（bearing=90°）", f"{east}/{len(offsets)} 帧偏东")
        link.send(cmd="stop")
        link.reply("stop")
        link.close()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            proc.kill()


def test_cli_play() -> None:
    print("[4] play --engine dry 命令行")
    cmd = [str(EXE)] if EXE and EXE.is_file() else [sys.executable, str(COMPANION / "superlocator.py")]
    cmd += ["play", "--file", str(COMPANION / "samples" / "route_campus.json"),
            "--kind", "route", "--engine", "dry", "--loop", "--interval", "0.2"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                            encoding="utf-8", errors="replace")
    lines: list[str] = []
    t0 = time.time()
    try:
        while time.time() - t0 < 10 and len(lines) < 8:
            line = proc.stdout.readline()
            if not line:
                break
            lines.append(line.strip())
            if line.strip().startswith("36.") or " 117." in line:
                pass
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
    coords = [l for l in lines if "," in l and "v=" in l]
    (ok if len(coords) >= 3 else bad)("坐标输出行", f"{len(coords)} 行，示例：{coords[0] if coords else '—'}")


def main() -> int:
    global EXE
    ap = argparse.ArgumentParser()
    ap.add_argument("--exe", type=Path, default=DEFAULT_EXE)
    ap.add_argument("--port", type=int, default=47811)
    args = ap.parse_args()
    EXE = args.exe if args.exe.is_file() else None

    # PyInstaller onefile 需要可写的临时目录；宿主环境里 %TEMP% 可能被拦，统一指到工作区
    tmp = ROOT / "build" / "tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    os.environ["TEMP"] = os.environ["TMP"] = os.environ["TMPDIR"] = str(tmp)

    print(f"被测对象：{EXE if EXE else 'python superlocator.py（源码）'}")
    print(f"文件大小：{(EXE.stat().st_size/1048576):.1f} MB" if EXE else "")
    test_cli()
    test_serve_track(args.port)
    test_jitter(args.port + 1)
    test_cli_play()

    print("\n" + "=" * 60)
    print(f"通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
    for f in FAIL:
        print("  ! " + f)
    return 0 if not FAIL else 1


if __name__ == "__main__":
    EXE: Path | None = None
    sys.exit(main())