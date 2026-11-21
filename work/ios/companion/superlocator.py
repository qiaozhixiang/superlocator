#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
superlocator.py —— 超级虚拟定位 · iOS 伴侣程序（Windows / macOS 通用）

作用：iPhone 上的 App 本身没有权限改写系统定位（iOS 沙盒限制），真正把坐标写进
系统的是「开发者服务」里的 DVT simulate-location 通道。本程序就是那条通道的
驱动器，同时把 Android 版里那套「轨迹重放 + 随机抖动 + 预设路径」算法原样复刻，
让 iPhone 也能按时间轴自动移动虚拟位置。

依赖：
    pip install pymobiledevice3      # 需要 USB 连接 + 开发者模式 + 挂载 DDI
    （不装也能跑：--engine dry 只打印坐标，用于验证轨迹与算法）

用法示例：
    python superlocator.py list
    python superlocator.py set --lat 36.667662 --lon 117.027707
    python superlocator.py play --file tracks/walk.json --radius 20 --bias 0.55
    python superlocator.py play --file routes/campus.json --offset 30 --loop
    python superlocator.py serve --port 47654          # 给 iPhone App 连
    # 同一个 serve 还会在 47655 上开网页版：手机 Safari 打开 http://<电脑IP>:47655/
    python superlocator.py serve --http-port 0        # 只要 TCP，不要网页版
    python superlocator.py gpx --file tracks/walk.json --out walk.gpx
    python superlocator.py clear
"""
from __future__ import annotations

import argparse
import asyncio
import http.server
import io
import json
import math
import os
import random
import select
import socket
import socketserver
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Tuple

from webapp_page import PAGE
import licensing
from pathlib import Path

APP_VERSION_FOR_LICENSE = "1.0.0"


def _license_dir() -> Path:
    base = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent
    return base / "license"


class LicenseCenter:
    """授权中心：台账（密钥/码/吊销）+ 本机激活状态。只活在电脑端。"""

    PRIVILEGED = frozenset({"set", "jitter", "play", "stop", "pause", "resume"})

    def __init__(self, directory, enabled: bool = True):
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.enabled = enabled
        self.ledger = licensing.Ledger(self.dir / "ledger.json")
        self.state = licensing.State(self.dir / "state.json")

    def status(self, device: str = "") -> dict:
        rec = self.state.get(device)
        return {
            "enabled": self.enabled,
            "active": self.is_active(device),
            "serial": rec.get("serial", 0),
            "devices": len(self.state.devices()),
        }

    def is_active(self, device: str) -> bool:
        """每次都回台账重算：吊销 / 删除立刻生效，不用重启也不用重新构建。"""
        if not self.enabled:
            return True
        rec = self.state.get(device)
        if not rec.get("serial") or not rec.get("code"):
            return False
        self.ledger.refresh()
        res = self.ledger.verify(rec["code"], rec.get("devHash") or None)
        return bool(res.get("ok")) and int(res.get("serial", -1)) == int(rec["serial"])

    def activate(self, code: str, dev_hash=None, device: str = "") -> dict:
        res = self.ledger.activate(code, dev_hash, client=device)
        if res.get("ok") and device:
            self.state.record(device, res["serial"], code.strip().upper(), dev_hash or "")
        return res

    def deactivate(self, device: str = "") -> None:
        self.state.drop(device or None)


class _Tee:
    """Duplicate console output into a log file (UTF-8, line flushed)."""

    def __init__(self, *streams):
        self.streams = [x for x in streams if x]

    def write(self, data):
        for st in self.streams:
            try:
                st.write(data)
                st.flush()
            except Exception:
                pass
        return len(data)

    def flush(self):
        for st in self.streams:
            try:
                st.flush()
            except Exception:
                pass

    def isatty(self):
        return False


APP_VERSION = "1.0.0"
DEFAULT_INTERVAL_MS = 100
SERVER_PORT = 47654
RELAY_PORT = 47656

# ---------------------------------------------------------------------------
# 几何
# ---------------------------------------------------------------------------


class Geo:
    R = 6371008.8

    @staticmethod
    def distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        p1, p2 = math.radians(lat1), math.radians(lat2)
        dp = p2 - p1
        dl = math.radians(lon2 - lon1)
        a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
        return 2 * Geo.R * math.asin(min(1.0, math.sqrt(a)))

    @staticmethod
    def bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        p1, p2 = math.radians(lat1), math.radians(lat2)
        dl = math.radians(lon2 - lon1)
        y = math.sin(dl) * math.cos(p2)
        x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
        return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0

    @staticmethod
    def offset(lat: float, lon: float, east_m: float, north_m: float) -> Tuple[float, float]:
        d_lat = north_m / 111132.92
        cos_lat = math.cos(math.radians(lat))
        d_lon = east_m / (111132.92 * max(0.02, cos_lat))
        return lat + d_lat, lon + d_lon

    @staticmethod
    def point_along(lat1: float, lon1: float, lat2: float, lon2: float, frac: float) -> Tuple[float, float]:
        d = Geo.distance(lat1, lon1, lat2, lon2)
        if d < 1e-6:
            return lat1, lon1
        b = Geo.bearing(lat1, lon1, lat2, lon2)
        east = d * frac * math.sin(math.radians(b))
        north = d * frac * math.cos(math.radians(b))
        return Geo.offset(lat1, lon1, east, north)


# ---------------------------------------------------------------------------
# 随机抖动（与 Android 版 Jitter.java 同一套公式）
# ---------------------------------------------------------------------------


class Jitter:
    """radius 米为半径，bias 为「权重偏于」强度 0~1，bearing 为目标方位角（None=随机）。"""

    def __init__(self, radius: float = 0.0, bias: float = 0.0, bearing: Optional[float] = None, seed: Optional[int] = None):
        self.radius = max(0.0, radius)
        self.bias = min(1.0, max(0.0, bias))
        self.rng = random.Random(seed)
        self.base_bearing = bearing if bearing is not None else self.rng.uniform(0, 360)
        self.base_mag = self.radius * self.bias * (0.5 + 0.5 * self.rng.random())
        self.tx = 0.0
        self.ty = 0.0
        self.cx = 0.0
        self.cy = 0.0
        self.next_resample = 0.0
        self.last_ms = 0

    def _resample(self, now_ms: float) -> None:
        spread = 180.0 * (1.0 - self.bias) + (3.0 if self.bias >= 0.999 else 12.0)
        theta = self.base_bearing + self.rng.gauss(0.0, spread)
        u = max(1e-6, self.rng.random())
        rayleigh = 0.55 * math.sqrt(-2.0 * math.log(u))
        mag = self.radius * (1.0 - 0.65 * self.bias) * rayleigh
        base_east = self.base_mag * math.sin(math.radians(self.base_bearing))
        base_north = self.base_mag * math.cos(math.radians(self.base_bearing))
        self.tx = base_east + mag * math.sin(math.radians(theta))
        self.ty = base_north + mag * math.cos(math.radians(theta))
        self.next_resample = now_ms + self.rng.uniform(4000, 9000)

    def step(self, now_ms: float) -> Tuple[float, float]:
        if self.radius <= 0.0:
            return 0.0, 0.0
        if self.next_resample == 0.0:
            self._resample(now_ms)
            self.last_ms = now_ms
            return self.tx, self.ty
        dt = max(0.0, (now_ms - self.last_ms) / 1000.0)
        self.last_ms = now_ms
        k = 1.0 - math.exp(-dt / 1.2) if dt > 0 else 0.0
        self.cx += (self.tx - self.cx) * k
        self.cy += (self.ty - self.cy) * k
        limit = self.radius * 1.5
        mag = math.hypot(self.cx, self.cy)
        if mag > limit and mag > 0:
            self.cx *= limit / mag
            self.cy *= limit / mag
        if now_ms >= self.next_resample:
            self._resample(now_ms)
        return self.cx, self.cy

    def describe(self) -> str:
        if self.radius <= 0:
            return "无抖动"
        side = "" if self.bias < 0.05 else ("强偏向" if self.bias >= 0.9 else "偏向")
        return f"半径 {self.radius:.0f}m · {side}{self.base_bearing:.0f}° · 权重 {self.bias * 100:.0f}%"


# ---------------------------------------------------------------------------
# 数据模型（与 iOS App 的 JSON 完全一致）
# ---------------------------------------------------------------------------


@dataclass
class TrackPoint:
    t: int          # 毫秒（相对起点）
    lat: float
    lng: float


@dataclass
class Track:
    id: str = ""
    name: str = "轨迹"
    groupId: str = "default"
    createdAt: int = 0
    intervalMs: int = 500
    points: List[TrackPoint] = field(default_factory=list)

    @property
    def duration_ms(self) -> int:
        return self.points[-1].t if self.points else 0

    def distance_m(self) -> float:
        total = 0.0
        for i in range(1, len(self.points)):
            a, b = self.points[i - 1], self.points[i]
            total += Geo.distance(a.lat, a.lng, b.lat, b.lng)
        return total

    @staticmethod
    def from_json(d: Dict[str, Any]) -> "Track":
        pts = [TrackPoint(int(p[0]), float(p[1]), float(p[2])) for p in d.get("points", [])]
        pts.sort(key=lambda p: p.t)
        return Track(
            id=d.get("id", ""),
            name=d.get("name", "轨迹"),
            groupId=d.get("groupId", d.get("group", "default")),
            createdAt=int(d.get("createdAt", 0)),
            intervalMs=int(d.get("intervalMs", DEFAULT_INTERVAL_MS * 5)),
            points=pts,
        )

    def to_json(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "groupId": self.groupId,
            "createdAt": self.createdAt,
            "intervalMs": self.intervalMs,
            "points": [[p.t, round(p.lat, 6), round(p.lng, 6)] for p in self.points],
        }


@dataclass
class RouteNode:
    lat: float
    lng: float
    speedMps: float = 0.0     # 0 = 跟随全局


@dataclass
class PresetRoute:
    id: str = ""
    name: str = "预设路径"
    createdAt: int = 0
    globalSpeed: float = 1.4
    offsetPercent: float = 20.0
    loop: bool = False
    nodes: List[RouteNode] = field(default_factory=list)

    def segment_lengths(self) -> List[float]:
        out = []
        for i in range(1, len(self.nodes)):
            a, b = self.nodes[i - 1], self.nodes[i]
            out.append(Geo.distance(a.lat, a.lng, b.lat, b.lng))
        return out

    def base_speed(self, seg: int) -> float:
        if 0 <= seg < len(self.nodes) and self.nodes[seg].speedMps > 0:
            return self.nodes[seg].speedMps
        return self.globalSpeed

    def from_track(self, t: Track) -> "PresetRoute":
        self.nodes = [RouteNode(p.lat, p.lng, 0.0) for p in t.points]
        return self

    @staticmethod
    def from_json(d: Dict[str, Any]) -> "PresetRoute":
        nodes = []
        for n in d.get("nodes", []):
            if isinstance(n, dict):
                nodes.append(RouteNode(float(n["lat"]), float(n["lng"]), float(n.get("speedMps", 0.0))))
            else:
                nodes.append(RouteNode(float(n[0]), float(n[1]), float(n[2]) if len(n) > 2 else 0.0))
        return PresetRoute(
            id=d.get("id", ""),
            name=d.get("name", "预设路径"),
            createdAt=int(d.get("createdAt", 0)),
            globalSpeed=float(d.get("globalSpeed", 1.4)),
            offsetPercent=float(d.get("offsetPercent", 20.0)),
            loop=bool(d.get("loop", False)),
            nodes=nodes,
        )

    def to_json(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "createdAt": self.createdAt,
            "globalSpeed": self.globalSpeed,
            "offsetPercent": self.offsetPercent,
            "loop": self.loop,
            "nodes": [[round(n.lat, 6), round(n.lng, 6), round(n.speedMps, 3)] for n in self.nodes],
        }


# ---------------------------------------------------------------------------
# 定位注入：三种引擎
# ---------------------------------------------------------------------------


class BaseProvider:
    name = "base"

    def open(self) -> None: ...
    def set_location(self, lat: float, lon: float) -> None: ...
    def clear(self) -> None: ...
    def close(self) -> None: ...


class DryProvider(BaseProvider):
    name = "dry"

    def __init__(self, verbose: bool = True):
        self.verbose = verbose
        self.last: Optional[Tuple[float, float]] = None

    def set_location(self, lat: float, lon: float) -> None:
        self.last = (lat, lon)
        if self.verbose:
            print(f"[dry] {lat:.6f}, {lon:.6f}", flush=True)



class RelayProvider(BaseProvider):
    """跑在服务器上：坐标转发给「插着 iPhone 的那台机器」上的 agent。

    协议：agent 主动连过来（能穿过 NAT），之后每行一个 JSON。
        server -> agent  {"op":"set","lat":..,"lon":..}
        agent  -> server {"ok":true} 或 {"ok":false,"error":".."}
    """

    name = "relay"

    def __init__(self, port: int = RELAY_PORT, token: str = "", verbose: bool = True):
        self.port = int(port)
        self.token = token or ""
        self.verbose = verbose
        self.sock = None
        self.conn = None
        self.peer = ""
        self.lock = threading.Lock()
        self.stop_evt = threading.Event()

    def open(self) -> None:
        if self.sock:
            return
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("0.0.0.0", self.port))
        srv.listen(4)
        self.sock = srv
        threading.Thread(target=self._accept_loop, daemon=True).start()
        print(f"[relay] 等本机 agent 连进来：端口 {self.port}"
              + ("（需要 token）" if self.token else ""), flush=True)

    def close(self) -> None:
        self.stop_evt.set()
        with self.lock:
            if self.conn:
                try:
                    self.conn[0].close()
                except Exception:
                    pass
                self.conn = None
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None

    def _accept_loop(self) -> None:
        assert self.sock is not None
        while not self.stop_evt.is_set():
            try:
                c, addr = self.sock.accept()
            except OSError:
                return
            threading.Thread(target=self._handshake, args=(c, addr), daemon=True).start()

    def _handshake(self, c, addr) -> None:
        f = c.makefile("rwb")
        try:
            hello = json.loads(f.readline().decode("utf-8") or "{}")
        except Exception:
            c.close()
            return
        if self.token and hello.get("token") != self.token:
            f.write((json.dumps({"ok": False, "error": "token 不对"}) + "\n").encode())
            f.flush()
            c.close()
            if self.verbose:
                print(f"[relay] 拒绝 {addr[0]}：token 不对", flush=True)
            return
        with self.lock:
            if self.conn:
                try:
                    self.conn[0].close()
                except Exception:
                    pass
            self.conn = (c, f)
            self.peer = addr[0]
        f.write((json.dumps({"ok": True, "msg": "relay agent connected"}) + "\n").encode())
        f.flush()
        if self.verbose:
            print(f"[relay] agent 已连接：{addr[0]}（engine={hello.get('engine')}）", flush=True)
        while not self.stop_evt.is_set():
            try:
                r, _, _ = select.select([c], [], [], 0.5)
            except OSError:
                break
            if not r:
                continue
            try:
                data = c.recv(64, socket.MSG_PEEK)   # 只探活，不把 set 的回复吃掉
            except OSError:
                break
            if data == b"":
                break
            c.recv(64)
        with self.lock:
            if self.conn and self.conn[0] is c:
                self.conn = None
        if self.verbose:
            print(f"[relay] agent 断开：{addr[0]}", flush=True)

    def set_location(self, lat: float, lon: float) -> None:
        with self.lock:
            if not self.conn:
                raise RuntimeError("relay: 还没有 agent 连接（本机那边要先把 agent 打开）")
            c, f = self.conn
            f.write((json.dumps({"op": "set", "lat": lat, "lon": lon}) + "\n").encode())
            f.flush()
            line = f.readline()
        if not line:
            self.conn = None
            raise RuntimeError("relay: agent 断开了")
        res = json.loads(line.decode("utf-8"))
        if not res.get("ok"):
            raise RuntimeError(res.get("error") or "relay: agent 报错")

    def clear(self) -> None:
        with self.lock:
            if not self.conn:
                return
            c, f = self.conn
            try:
                f.write((json.dumps({"op": "clear"}) + "\n").encode())
                f.flush()
            except Exception:
                pass


class CliProvider(BaseProvider):
    """Fallback: one `simulate-location set` process per point (<= 1 Hz)."""

    name = "cli"

    def __init__(self, udid: Optional[str] = None, rsd: Optional[str] = None, verbose: bool = False):
        self.udid = udid
        self.rsd = rsd
        self.verbose = verbose

    def _device_opts(self) -> List[str]:
        if self.rsd:
            host, _, port = str(self.rsd).partition(":")
            return ["--rsd", host, port or "49152"]
        if self.udid:
            return ["--udid", self.udid]
        return []

    def _base(self) -> List[str]:
        return [sys.executable, "-m", "pymobiledevice3", "developer", "dvt", "simulate-location"]

    def set_location(self, lat: float, lon: float) -> None:
        cmd = self._base() + ["set"] + self._device_opts() + ["--", f"{lat:.7f}", f"{lon:.7f}"]
        if self.verbose:
            print(" ".join(cmd), flush=True)
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            out, err = proc.communicate(timeout=2.0)
        except subprocess.TimeoutExpired:
            proc.terminate()
            try:
                out, err = proc.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                out, err = "", ""
        if proc.returncode not in (0, -15, 1) and (err or "").strip():
            raise RuntimeError((err or out).strip()[:300])

    def clear(self) -> None:
        proc = subprocess.Popen(self._base() + ["clear"] + self._device_opts(),
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True)
        try:
            proc.communicate(timeout=6.0)
        except subprocess.TimeoutExpired:
            proc.terminate()


def _friendly_usb(exc: Exception) -> str:
    text = str(exc)
    if "usbmuxd" in text or "usbmux" in text:
        return ("usbmuxd 未运行：先装 iTunes 或 Apple Devices（微软商店版即可），"
                "插好数据线并在手机上点「信任」，然后再试")
    if "no device" in text.lower() or "device not found" in text.lower():
        return "没有找到 iPhone：换原装数据线、重插、手机上点「信任此电脑」"
    return text


def _parse_rsd(value: Optional[str]) -> Optional[Tuple[str, int]]:
    if not value:
        return None
    host, _, port = str(value).partition(":")
    try:
        return host, int(port or 49152)
    except ValueError:
        return host, 49152


class LibProvider(BaseProvider):
    """Persistent DVT session driven by a private asyncio loop (pymobiledevice3 11.x)."""

    name = "lib"

    def __init__(self, udid: Optional[str] = None, rsd: Optional[str] = None, verbose: bool = False):
        self.udid = udid
        self.rsd = _parse_rsd(rsd)
        self.verbose = verbose
        self._loop = None
        self._thread = None
        self._sp = None
        self._dvt = None
        self._loc = None

    # ---- asyncio plumbing -------------------------------------------------
    def _ensure_loop(self) -> None:
        if self._loop is not None:
            return
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, name="dvt-loop", daemon=True)
        self._thread.start()

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def _call(self, coro, timeout: float = 30.0):
        self._ensure_loop()
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result(timeout)

    async def _open(self) -> None:
        from pymobiledevice3.lockdown import create_using_usbmux  # type: ignore
        from pymobiledevice3.services.dvt.instruments.dvt_provider import DvtProvider  # type: ignore
        from pymobiledevice3.services.dvt.instruments.location_simulation import LocationSimulation  # type: ignore

        if self.rsd:
            from pymobiledevice3.remote.remote_service_discovery import RemoteServiceDiscoveryService  # type: ignore
            self._sp = RemoteServiceDiscoveryService(self.rsd)
            await self._sp.connect()
        elif self.udid:
            try:
                self._sp = await create_using_usbmux(serial=self.udid)
            except Exception as exc:
                raise RuntimeError(_friendly_usb(exc)) from exc
        else:
            try:
                self._sp = await create_using_usbmux()
            except Exception as exc:
                raise RuntimeError(_friendly_usb(exc)) from exc
        self._dvt = DvtProvider(self._sp)
        await self._dvt.__aenter__()
        self._loc = LocationSimulation(self._dvt)
        await self._loc.__aenter__()
        if self.verbose:
            print(f"[lib] DVT session ready (udid={self.udid or 'auto'})", flush=True)

    async def _close(self) -> None:
        for obj in (self._loc, self._dvt):
            if obj is None:
                continue
            try:
                await obj.__aexit__(None, None, None)
            except Exception:
                pass
        self._loc = None
        self._dvt = None
        self._sp = None

    # ---- BaseProvider -----------------------------------------------------
    def open(self) -> None:
        self._ensure_loop()
        self._call(self._open())

    def set_location(self, lat: float, lon: float) -> None:
        if self._loc is None:
            self.open()
        try:
            self._call(self._loc.set(lat, lon), timeout=8.0)
        except Exception:
            try:
                self._call(self._close(), timeout=8.0)
            except Exception:
                self._loc = None
            raise

    def clear(self) -> None:
        if self._loc is None:
            return
        try:
            self._call(self._loc.clear(), timeout=8.0)
        except Exception:
            pass

    def close(self) -> None:
        try:
            if self._loc is not None or self._dvt is not None:
                self._call(self._close(), timeout=10.0)
        except Exception:
            pass
        if self._loop is not None:
            try:
                self._loop.call_soon_threadsafe(self._loop.stop)
            except Exception:
                pass


def make_provider(engine: str, udid: Optional[str], rsd: Optional[str], quiet: bool) -> BaseProvider:
    if engine == "lib":
        return LibProvider(udid=udid, rsd=rsd, verbose=not quiet)
    if engine == "cli":
        return CliProvider(udid=udid, rsd=rsd, verbose=not quiet)
    return DryProvider(verbose=not quiet)


# ---------------------------------------------------------------------------
# 播放器：轨迹 / 预设路径共用一套时间轴
# ---------------------------------------------------------------------------


class Player:
    def __init__(self, provider: BaseProvider, hz: float = 10.0, on_tick=None):
        self.provider = provider
        self.interval = 1.0 / max(0.2, hz)
        self.on_tick = on_tick
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._paused = False
        self._mode: Optional[str] = None       # "track" | "route"
        self._track: Optional[Track] = None
        self._route: Optional[PresetRoute] = None
        self._speed = 1.0
        self._loop = False
        self._jitter = Jitter(0, 0, None)
        self._offset = 0.0
        self._seg_lens: List[float] = []
        self._cum: List[float] = []
        self._total = 0.0
        self._travel = 0.0
        self._seg = 0
        self._seg_speed = 0.0
        self._seg_until = 0.0
        self._started = 0.0
        self._base_lat = 0.0
        self._base_lon = 0.0
        self._out_lat = 0.0
        self._out_lon = 0.0
        self.progress = 0.0
        self.loops = 0
        self.pushes = 0
        self.last_error = ""

    # -- 配置 ------------------------------------------------------------
    def load_track(self, track: Track, speed: float = 1.0, loop: bool = False,
                   radius: float = 0.0, bias: float = 0.0, bearing: Optional[float] = None) -> None:
        with self._lock:
            self._mode = "track"
            self._track = track
            self._speed = max(0.1, min(20.0, speed))
            self._loop = loop
            self._jitter = Jitter(radius, bias, bearing)
            self._started = 0.0
            self.progress = 0.0

    def load_route(self, route: PresetRoute, offset_percent: float = 20.0, loop: bool = False,
                   radius: float = 0.0, bias: float = 0.0, bearing: Optional[float] = None) -> None:
        with self._lock:
            self._mode = "route"
            self._route = route
            self._offset = max(0.0, min(90.0, offset_percent))
            self._loop = loop
            self._jitter = Jitter(radius, bias, bearing)
            self._seg_lens = route.segment_lengths()
            self._cum = [0.0]
            for seg in self._seg_lens:
                self._cum.append(self._cum[-1] + seg)
            self._total = self._cum[-1]
            self._travel = 0.0
            self._seg = 0
            self._seg_until = 0.0
            self.progress = 0.0
            self.loops = 0

    # -- 生命周期 --------------------------------------------------------
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            self._running = True
            self._paused = False
            return
        self._running = True
        self._paused = False
        self._started = time.monotonic()
        self._prime()
        self._thread = threading.Thread(target=self._loop_thread, name="player", daemon=True)
        self._thread.start()

    def pause(self) -> None:
        self._paused = True

    def resume(self) -> None:
        if self._paused:
            self._started = time.monotonic() - self._elapsed_before_pause
            self._paused = False

    @property
    def _elapsed_before_pause(self) -> float:
        return getattr(self, "_paused_elapsed", 0.0)

    def stop(self) -> None:
        self._running = False
        t = self._thread
        if t and t.is_alive() and t is not threading.current_thread():
            t.join(timeout=1.5)
        self._thread = None
        try:
            self.provider.clear()
        except Exception as exc:      # noqa: BLE001
            self.last_error = str(exc)[:200]

    def is_running(self) -> bool:
        return self._running and not self._paused

    # -- 内部 ------------------------------------------------------------
    def _prime(self) -> None:
        if self._mode == "track" and self._track and self._track.points:
            p = self._track.points[0]
            self._push_base(p.lat, p.lng)
        elif self._mode == "route" and self._route and self._route.nodes:
            n = self._route.nodes[0]
            self._push_base(n.lat, n.lng)

    def _push_base(self, lat: float, lon: float) -> None:
        self._base_lat, self._base_lon = lat, lon
        east, north = self._jitter.step(time.monotonic() * 1000.0)
        out = Geo.offset(lat, lon, east, north)
        self._out_lat, self._out_lon = out
        try:
            self.provider.set_location(out[0], out[1])
            self.pushes += 1
        except Exception as exc:      # noqa: BLE001
            self.last_error = str(exc)[:200]
        if self.on_tick:
            self.on_tick(self._snapshot())

    def _snapshot(self) -> Dict[str, Any]:
        return {
            "mode": self._mode,
            "lat": round(self._out_lat, 7),
            "lon": round(self._out_lon, 7),
            "baseLat": round(self._base_lat, 7),
            "baseLon": round(self._base_lon, 7),
            "progress": round(self.progress, 4),
            "speed": round(self._seg_speed, 3),
            "segment": self._seg,
            "loops": self.loops,
            "pushes": self.pushes,
            "jitter": self._jitter.describe(),
            "error": self.last_error,
        }

    def _position_at(self, ms: float) -> Tuple[float, float]:
        pts = self._track.points if self._track else []
        if not pts:
            return self._base_lat, self._base_lon
        if ms <= pts[0].t:
            return pts[0].lat, pts[0].lng
        if ms >= pts[-1].t:
            return pts[-1].lat, pts[-1].lng
        lo, hi = 0, len(pts) - 1
        while lo + 1 < hi:
            mid = (lo + hi) // 2
            if pts[mid].t <= ms:
                lo = mid
            else:
                hi = mid
        a, b = pts[lo], pts[lo + 1]
        span = max(1, b.t - a.t)
        frac = (ms - a.t) / span
        # Catmull-Rom：用前后各一点做平滑，越界时退化为端点
        p0 = pts[max(0, lo - 1)]
        p1, p2 = a, b
        p3 = pts[min(len(pts) - 1, lo + 2)]
        u = frac
        u2, u3 = u * u, u * u * u
        lat = 0.5 * ((2 * p1.lat) + (-p0.lat + p2.lat) * u
                     + (2 * p0.lat - 5 * p1.lat + 4 * p2.lat - p3.lat) * u2
                     + (-p0.lat + 3 * p1.lat - 3 * p2.lat + p3.lat) * u3)
        lon = 0.5 * ((2 * p1.lng) + (-p0.lng + p2.lng) * u
                     + (2 * p0.lng - 5 * p1.lng + 4 * p2.lng - p3.lng) * u2
                     + (-p0.lng + 3 * p1.lng - 3 * p2.lng + p3.lng) * u3)
        return lat, lon

    def _route_step(self, dt: float) -> Tuple[float, float]:
        route = self._route
        if not route or self._total <= 0:
            return self._base_lat, self._base_lon
        now = time.monotonic()
        if now >= self._seg_until or self._seg_speed <= 0:
            factor = 1.0 + (random.random() * 2 - 1) * (self._offset / 100.0)
            self._seg_speed = max(0.2, min(25.0, route.base_speed(self._seg) * factor))
            self._seg_until = now + 2.5
        self._travel += self._seg_speed * dt
        if self._travel >= self._total:
            if self._loop:
                self._travel %= self._total
                self.loops += 1
            else:
                self._travel = self._total
        # 定位所在段
        seg = 0
        while seg + 1 < len(self._cum) and self._cum[seg + 1] < self._travel:
            seg += 1
        if seg != self._seg:
            self._seg = seg
            self._seg_until = 0.0
        length = self._seg_lens[seg] if seg < len(self._seg_lens) else 0.0
        frac = 0.0 if length <= 0 else (self._travel - self._cum[seg]) / length
        a, b = route.nodes[seg], route.nodes[min(seg + 1, len(route.nodes) - 1)]
        self.progress = 0.0 if self._total <= 0 else min(1.0, self._travel / self._total)
        return Geo.point_along(a.lat, a.lng, b.lat, b.lng, min(1.0, max(0.0, frac)))

    def _loop_thread(self) -> None:
        last = time.monotonic()
        while self._running:
            if self._paused:
                time.sleep(0.05)
                last = time.monotonic()
                continue
            now = time.monotonic()
            dt = min(0.5, max(0.0, now - last))
            last = now
            try:
                if self._mode == "track" and self._track:
                    ms = (now - self._started) * 1000.0 * self._speed
                    dur = float(self._track.duration_ms)
                    if dur > 0:
                        if ms > dur:
                            if self._loop:
                                self._started = now - (ms % dur) / 1000.0 / self._speed
                                ms = ms % dur
                            else:
                                ms = dur
                                self._running = False
                        self.progress = 0.0 if dur <= 0 else min(1.0, ms / dur)
                    lat, lon = self._position_at(ms)
                    self._push_base(lat, lon)
                elif self._mode == "route":
                    lat, lon = self._route_step(dt)
                    self._push_base(lat, lon)
            except Exception as exc:      # noqa: BLE001
                self.last_error = str(exc)[:200]
            time.sleep(self.interval)
        self._running = False


# ---------------------------------------------------------------------------
# 给 iPhone App 用的 TCP 服务（行分隔 JSON）
# ---------------------------------------------------------------------------


class _Handler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        srv: "BridgeServer" = self.server.bridge       # type: ignore[attr-defined]
        peer = self.client_address
        print(f"[serve] 客户端接入 {peer}", flush=True)
        self.wfile.write(self._line({"ok": True, "event": "hello", "version": APP_VERSION, "device": srv.device_name}))

        def on_tick(snap: Dict[str, Any]) -> None:
            try:
                self.wfile.write(self._line({"event": "position", **snap}))
            except Exception:
                pass

        srv.player.on_tick = on_tick
        try:
            for raw in self.rfile:
                try:
                    msg = json.loads(raw.decode("utf-8").strip() or "{}")
                except json.JSONDecodeError:
                    self.wfile.write(self._line({"ok": False, "error": "bad json"}))
                    continue
                reply = srv.handle(msg)
                self.wfile.write(self._line(reply))
        except (ConnectionError, OSError):
            pass
        finally:
            print(f"[serve] 客户端断开 {peer}", flush=True)
            srv.player.on_tick = None

    @staticmethod
    def _line(obj: Dict[str, Any]) -> bytes:
        return (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8")


class BridgeServer(socketserver.ThreadingTCPServer):
    # Windows 上 SO_REUSEADDR 会让两个进程绑同一端口（页面串到旧进程），必须关掉
    allow_reuse_address = False
    daemon_threads = True

    def __init__(self, addr, player: Player, device_name: str = "", license_center: "LicenseCenter | None" = None):
        super().__init__(addr, _Handler)
        self.bridge = self
        self.player = player
        self.device_name = device_name
        self.license = license_center

    def handle(self, msg: Dict[str, Any]) -> Dict[str, Any]:
        cmd = str(msg.get("cmd", "")).lower()
        device = str(msg.get("device", "") or "")
        try:
            if cmd == "ping":
                return {"ok": True, "cmd": cmd, "version": APP_VERSION}
            if cmd == "hello":
                out = {"ok": True, "cmd": cmd, "version": APP_VERSION}
                if self.license is not None:
                    out["license"] = self.license.status(device)
                return out
            if cmd == "license_status":
                if self.license is None:
                    return {"ok": True, "cmd": cmd, "enabled": False, "active": True}
                return {"ok": True, "cmd": cmd, **self.license.status(device)}
            if cmd == "license_activate":
                if self.license is None:
                    return {"ok": True, "cmd": cmd, "enabled": False, "active": True}
                res = self.license.activate(str(msg.get("code", "")), msg.get("deviceHash"), device)
                return {"ok": bool(res.get("ok")), "cmd": cmd, "message": res.get("message", ""),
                        "serial": res.get("serial", 0), **self.license.status(device)}
            if self.license is not None and self.license.enabled                     and cmd in LicenseCenter.PRIVILEGED and not self.license.is_active(device):
                return {"ok": False, "cmd": cmd, "needLicense": True,
                        "error": "未激活：先在本程序里输入激活码"}
            if cmd == "set":
                lat, lon = float(msg["lat"]), float(msg["lon"])
                self.player.provider.set_location(lat, lon)
                return {"ok": True, "cmd": "set", "lat": lat, "lon": lon}
            if cmd == "jitter":
                self.player._jitter = Jitter(                       # noqa: SLF001
                    float(msg.get("radius", 0.0)),
                    float(msg.get("bias", 0.0)),
                    None if msg.get("bearing") in (None, "") else float(msg["bearing"]),
                )
                return {"ok": True, "cmd": "jitter", "desc": self.player._jitter.describe()}  # noqa: SLF001
            if cmd == "play":
                payload = msg.get("payload") or {}
                kind = payload.get("kind", "track")
                if kind == "route":
                    route = PresetRoute.from_json(payload)
                    self.player.load_route(
                        route,
                        offset_percent=float(payload.get("offsetPercent", 20.0)),
                        loop=bool(payload.get("loop", False)),
                        radius=float(payload.get("radius", 0.0)),
                        bias=float(payload.get("bias", 0.0)),
                        bearing=payload.get("bearing"),
                    )
                else:
                    track = Track.from_json(payload)
                    self.player.load_track(
                        track,
                        speed=float(payload.get("speed", 1.0)),
                        loop=bool(payload.get("loop", False)),
                        radius=float(payload.get("radius", 0.0)),
                        bias=float(payload.get("bias", 0.0)),
                        bearing=payload.get("bearing"),
                    )
                self.player.start()
                return {"ok": True, "cmd": "play", "kind": kind}
            if cmd in ("pause", "resume", "stop"):
                getattr(self.player, cmd)()
                return {"ok": True, "cmd": cmd}
            if cmd == "status":
                return {"ok": True, "cmd": "status", **self.player._snapshot(),      # noqa: SLF001
                        "running": self.player.is_running()}
            return {"ok": False, "error": f"unknown cmd {cmd}"}
        except Exception as exc:      # noqa: BLE001
            return {"ok": False, "cmd": cmd, "error": str(exc)[:300]}


# ---------------------------------------------------------------------------
# 网页版：iPhone Safari 直接打开，无需安装 / 无需签名
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------- 局域网彩蛋
_MDNS = None          # (Zeroconf, ServiceInfo)


def mdns_start(http_port: int) -> str:
    """广播 superlocator.local:http_port，手机不用记 IP。失败返回空串。"""
    global _MDNS
    try:
        from zeroconf import Zeroconf, ServiceInfo
    except Exception:
        return ""
    try:
        ip = _lan_ip()
        info = ServiceInfo(
            "_http._tcp.local.",
            "SuperLocator._http._tcp.local.",
            addresses=[socket.inet_aton(ip)],
            port=int(http_port),
            properties={"path": "/", "app": "superlocator"},
            server="superlocator.local.",
        )
        zc = Zeroconf()
        zc.register_service(info)
        _MDNS = (zc, info)
        return "superlocator.local"
    except Exception:
        return ""


def mdns_stop() -> None:
    global _MDNS
    if not _MDNS:
        return
    try:
        zc, info = _MDNS
        zc.unregister_service(info)
        zc.close()
    except Exception:
        pass
    _MDNS = None


def qr_svg(url: str) -> bytes:
    """不依赖 Pillow 的二维码：qrcode 的 SVG 工厂。"""
    import qrcode
    import qrcode.image.svg

    img = qrcode.make(url, image_factory=qrcode.image.svg.SvgPathImage, border=2, box_size=10)
    buf = io.BytesIO()
    img.save(buf)
    return buf.getvalue()


def qr_png(url: str) -> bytes:
    """有 Pillow 就走 PNG（相机识别更快），没有回退 SVG。"""
    try:
        import qrcode
        from PIL import Image  # noqa: F401
    except Exception:
        return b""
    img = qrcode.make(url, border=2, box_size=8)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()



def _print_qr(text: str) -> None:
    """不依赖终端能力的二维码：方块模式优先，编码不支持就退回 # 号。"""
    import qrcode

    qr = qrcode.QRCode(border=1)
    qr.add_data(text)
    qr.make(fit=True)
    m = qr.get_matrix()
    enc = (sys.stdout.encoding or "ascii").lower()
    try:
        "█▀▄".encode(enc)
        fancy = True
    except Exception:
        fancy = False
    if fancy:
        for y in range(0, len(m), 2):
            row = []
            for x in range(len(m)):
                top = m[y][x]
                bot = m[y + 1][x] if y + 1 < len(m) else False
                row.append("█" if top and bot else "▀" if top else "▄" if bot else " ")
            print("".join(row))
    else:
        for y in range(0, len(m), 2):
            for x in range(len(m)):
                top = m[y][x]
                bot = m[y + 1][x] if y + 1 < len(m) else False
                print("#" if top else " ", end="")
                print("#" if bot else " ", end="")
            print()

def _print_banner(http_port: int) -> None:
    ip = _lan_ip()
    name = mdns_start(http_port)
    urls = []
    if name:
        urls.append(f"http://{name}:{http_port}/")
    urls.append(f"http://{ip}:{http_port}/")

    line = "=" * 60
    print("")
    print(line)
    print("  超级虚拟定位 · 电脑端已就绪（这个窗口不要关）")
    print("  iPhone 用 Safari 打开下面任意一行：")
    for u in urls:
        print(f"      {u}")
    print("  手机上直接扫码也行：相机对着下面这块方块")
    print(line)
    try:
        _print_qr(urls[0])
    except Exception as exc:
        print(f"  （二维码没画出来：{exc}；手打上面地址即可）")
    print(line)
    print("  首次使用：手机页面顶部粘激活码 → 点「激活」→ 就能选轨迹 / 路径")
    print(line)
    print("")



class _WebHandler(http.server.BaseHTTPRequestHandler):
    server_version = "SuperLocatorWeb/" + APP_VERSION

    def log_message(self, fmt, *args):   # 关掉每请求一行日志
        pass

    def _send(self, body: bytes, ctype: str, code: int = 200) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _json(self, obj: Dict[str, Any], code: int = 200) -> None:
        self._send(json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8", code)

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        bridge = self.server.bridge            # type: ignore[attr-defined]
        if path in ("/", "/app", "/index.html"):
            self._send(PAGE.encode("utf-8"), "text/html; charset=utf-8")
            return
        if path in ("/qr.png", "/qr.svg"):
            port = int(self.server.server_address[1])          # type: ignore[attr-defined]
            url = f"http://{_lan_ip()}:{port}/"
            try:
                png = qr_png(url) if path.endswith(".png") else b""
                if png:
                    self._send(png, "image/png")
                else:
                    self._send(qr_svg(url), "image/svg+xml")
            except Exception as exc:                            # 二维码坏了也不能连累页面
                html = (f"<html><body style='font:16px -apple-system;padding:24px'>"
                        f"<p>二维码生成失败：{exc}</p><p>直接在 Safari 输入 <b>{url}</b></p></body></html>")
                self._send(html.encode("utf-8"), "text/html; charset=utf-8", 200)
            return
        if path == "/api/status":
            self._json({"ok": True, **bridge.player._snapshot(),          # noqa: SLF001
                        "running": bridge.player.is_running()})
            return
        if path == "/api/license/status":
            lic = getattr(bridge, "license", None)
            dev = ""
            if "?" in self.path:
                q = dict(kv.split("=", 1) for kv in self.path.split("?", 1)[1].split("&") if "=" in kv)
                dev = q.get("device", "")
            if lic is None:
                self._json({"ok": True, "enabled": False, "active": True})
            else:
                self._json({"ok": True, **lic.status(dev)})
            return
        if path == "/favicon.ico":
            self._send(b"", "image/x-icon", 204)
            return
        self._json({"ok": False, "error": "not found"}, 404)

    def do_POST(self) -> None:
        path = self.path.split("?", 1)[0]
        bridge = self.server.bridge            # type: ignore[attr-defined]
        if path == "/api/license/activate":
            try:
                n = int(self.headers.get("Content-Length") or 0)
                msg = json.loads(self.rfile.read(n).decode("utf-8") or "{}")
            except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
                self._json({"ok": False, "error": "bad json"}, 400)
                return
            self._json(bridge.handle({"cmd": "license_activate", "code": msg.get("code", ""),
                                      "deviceHash": msg.get("deviceHash"), "device": msg.get("device", "")}))
            return
        if path != "/api/cmd":
            self._json({"ok": False, "error": "not found"}, 404)
            return
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = 0
        try:
            msg = json.loads(self.rfile.read(n).decode("utf-8") or "{}")
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._json({"ok": False, "error": "bad json"}, 400)
            return
        self._json(bridge.handle(msg))


class WebBridge(http.server.ThreadingHTTPServer):
    allow_reuse_address = False
    daemon_threads = True

    def __init__(self, addr, bridge: "BridgeServer"):
        super().__init__(addr, _WebHandler)
        self.bridge = bridge


def _lan_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.3)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return "127.0.0.1"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def cmd_list(args) -> int:
    try:
        from pymobiledevice3.usbmux import list_devices   # type: ignore
    except Exception:
        print("未安装 pymobiledevice3：pip install pymobiledevice3")
        return 1
    devs = list_devices()
    if not devs:
        print("没有检测到 iOS 设备（检查 USB、信任此电脑、开发者模式）")
        return 1
    for d in devs:
        print(f"{d.serial}  {getattr(d, 'connection_type', 'usb')}")
    return 0


def _read_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def cmd_set(args) -> int:
    provider = make_provider(args.engine, args.udid, args.rsd, args.quiet)
    provider.open()
    provider.set_location(args.lat, args.lon)
    print(f"已设置 {args.lat:.6f}, {args.lon:.6f}（engine={provider.name}）")
    return 0


def cmd_clear(args) -> int:
    provider = make_provider(args.engine, args.udid, args.rsd, args.quiet)
    provider.open()
    provider.clear()
    print("已清除虚拟位置")
    return 0


def cmd_play(args) -> int:
    data = _read_json(args.file)
    provider = make_provider(args.engine, args.udid, args.rsd, args.quiet)
    try:
        provider.open()
    except Exception as exc:
        print(f"[!] device not ready: {exc}")
    hz = args.hz
    if getattr(args, "interval", 0) and args.interval > 0:
        hz = 1.0 / args.interval
    player = Player(provider, hz=hz, on_tick=None if args.quiet else (lambda s: print(
        f"{s['progress'] * 100:5.1f}%  {s['lat']:.6f},{s['lon']:.6f}  v={s['speed']:.2f}m/s  "
        f"seg={s['segment']}  {s['jitter']}", flush=True)))
    kind = getattr(args, "kind", "auto")
    if kind == "route" or (kind == "auto" and "nodes" in data):
        player.load_route(PresetRoute.from_json(data), offset_percent=args.offset,
                          loop=args.loop or bool(data.get("loop", False)),
                          radius=args.radius, bias=args.bias, bearing=args.bearing)
    else:
        player.load_track(Track.from_json(data), speed=args.speed,
                          loop=args.loop, radius=args.radius, bias=args.bias, bearing=args.bearing)
    player.start()
    try:
        while player._running:        # noqa: SLF001
            time.sleep(0.2)
    except KeyboardInterrupt:
        print("\n中断")
    finally:
        player.stop()
    print(f"结束：push {player.pushes} 次，循环 {player.loops} 次"
          + (f"，错误 {player.last_error}" if player.last_error else ""))
    return 0


def _busy_ports(ports) -> List[int]:
    busy = []
    for port in ports:
        sock = socket.socket()
        try:
            sock.bind(("0.0.0.0", int(port)))
        except OSError:
            busy.append(int(port))
        finally:
            sock.close()
    return busy


def cmd_serve(args) -> int:
    if args.engine == "relay":
        provider = RelayProvider(getattr(args, "relay_port", RELAY_PORT),
                                 getattr(args, "relay_token", "") or "", verbose=not args.quiet)
    else:
        provider = make_provider(args.engine, args.udid, args.rsd, args.quiet)
    try:
        provider.open()
    except Exception as exc:
        print(f"[!] device not ready at startup: {exc}")
        print("    server keeps running; the first location push will retry the connection")
    player = Player(provider, hz=args.hz)
    center = None
    if not getattr(args, "no_license", False):
        center = LicenseCenter(args.license_dir or _license_dir())
        st = center.status()
        print(f"授权中心：{center.dir}（台账 {len(center.ledger.data.get('codes', []))} 个码，"
              f"已激活设备 {st['devices']} 台）")
        if not center.ledger.data.get("codes"):
            print("  还没有激活码，先跑：superlocator license keygen --universal --note 首发")
    else:
        print("授权：已关闭（--no-license，仅用于自测）")
    busy = _busy_ports([args.port] + ([args.http_port] if args.http_port else []))
    if busy:
        msg = "、".join(str(x) for x in busy)
        print(f"[!] 端口 {msg} 已被占用 —— 多半是上一次的窗口还开着。")
        print("    解决：任务管理器结束 superlocator.exe，或先关掉那个黑窗口，再启动本程序。")
        _hold_window()
        return 2
    srv = BridgeServer((args.host, args.port), player, device_name=args.udid or "", license_center=center)
    print(f"监听 {args.host}:{args.port}（engine={provider.name}），在 iPhone App 里填这个地址")
    if args.http_port:
        web = WebBridge((args.host, args.http_port), srv)
        threading.Thread(target=web.serve_forever, daemon=True).start()
        _print_banner(args.http_port)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n退出")
    finally:
        player.stop()
        mdns_stop()
        srv.server_close()
    return 0


def cmd_doctor(args) -> int:
    """双击 exe 打不开时的自查：环境、临时目录、台账、引擎、端口。"""
    import platform, shutil, socket, tempfile, sys as _sys
    print("== 超级虚拟定位 · 电脑端自检 ==")
    print(f"版本 {APP_VERSION} · Python {platform.python_version()} · {platform.system()} {platform.release()}")
    print(f"打包方式 {'PyInstaller 打包' if getattr(_sys, 'frozen', False) else '源码运行'}")
    print(f"程序位置 {Path(_sys.executable).parent}")
    ok = True

    # 1) 临时目录：单文件版要在这里解压，权限不足就会“闪退”
    tmp = Path(os.environ.get("TEMP") or os.environ.get("TMP") or tempfile.gettempdir())
    try:
        tmp.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=tmp, delete=True):
            pass
        print(f"[OK] 临时目录可写 {tmp}")
    except Exception as exc:
        ok = False
        print(f"[!!] 临时目录不可写 {tmp} → {exc}")
        print("     解决：右键 exe → 属性 → 解除锁定；或把整个文件夹放到 D:/SuperLocator/ 再运行")

    # 2) 工作目录（台账、日志都写这里）
    here = Path(_sys.executable).parent if getattr(_sys, "frozen", False) else Path(__file__).resolve().parent
    try:
        probe = here / ".write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        print(f"[OK] 程序目录可写 {here}")
    except Exception as exc:
        ok = False
        print(f"[!!] 程序目录不可写 {here} → {exc}")
        print("     解决：把整个文件夹放到 D:/SuperLocator/ 或桌面，不要放在 Program Files 或 C: 根目录")

    # 3) 授权台账
    lic_dir = Path(getattr(args, "license_dir", None) or _license_dir())
    led_path = lic_dir / "ledger.json"
    try:
        led = licensing.Ledger(led_path)
        print(f"[OK] 授权台账 {led_path}（码 {len(led.data.get('codes', []))} 条 / 吊销 {len(led.data.get('revoked', []))} 条）")
    except Exception as exc:
        ok = False
        print(f"[!!] 授权台账读不出来 {led_path} → {exc}")

    # 4) 写坐标引擎（没有它就只能“算”不能“写”）
    have_mod = False
    try:
        import pymobiledevice3  # noqa: F401
        have_mod = True
    except Exception:
        pass
    cli = shutil.which("pymobiledevice3")
    if have_mod or cli:
        print(f"[OK] pymobiledevice3 可用 {'（模块）' if have_mod else ''}{'（命令 ' + cli + '）' if cli else ''}")
    else:
        print("[..] pymobiledevice3 未安装 —— 只有 dist 里的 exe 不够，需要它才能写 iPhone 定位")
        print("     解决：装 Python 3.10+ 后执行  pip install pymobiledevice3")

    # 5) usbmuxd（iPhone 的 USB 通道）
    try:
        probe = socket.create_connection(("127.0.0.1", 27015), timeout=1.5)
        probe.close()
        print("[OK] usbmuxd（iTunes / Apple Devices 驱动）可连 127.0.0.1:27015")
    except OSError:
        print("[!!] usbmuxd 未运行 → 装 iTunes 或 Apple Devices（微软商店版），否则连不上 iPhone")

    # 6) 端口占用
    for port in (SERVER_PORT, SERVER_PORT + 1):
        s = socket.socket()
        try:
            s.bind(("0.0.0.0", port))
            print(f"[OK] 端口 {port} 空闲")
        except OSError as exc:
            ok = False
            print(f"[!!] 端口 {port} 被占用 → {exc}（先关掉已经在跑的 superlocator.exe）")
        finally:
            s.close()

    print("")
    print("下一步：")
    print("  1) 双击 start-service.bat → 看到「监听 0.0.0.0:47654」就不要关这个黑窗口")
    print("  2) iPhone Safari 打开 http://<电脑IP>:47655/ ，或装 App 后连同一网段")
    print("  3) 还是秒退？把「superlocator.log」里最后 20 行发我")
    return 0 if ok else 1


def cmd_gpx(args) -> int:
    data = _read_json(args.file)
    track = Track.from_json(data)
    body = "\n".join(
        f'      <trkpt lat="{p.lat:.6f}" lon="{p.lng:.6f}"><time>{_iso(p.t)}</time></trkpt>'
        for p in track.points
    )
    gpx = ('<?xml version="1.0" encoding="UTF-8"?>\n'
           '<gpx version="1.1" creator="SuperLocator" xmlns="http://www.topografix.com/GPX/1/1">\n'
           f'  <trk><name>{track.name}</name><trkseg>\n{body}\n  </trkseg></trk>\n</gpx>\n')
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(gpx)
    print(f"已写出 {args.out}（{len(track.points)} 点，{track.distance_m():.1f} 米）")
    return 0


def _iso(ms: int) -> str:
    base = 1700000000 + ms // 1000
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(base))


def cmd_license(args) -> int:
    center = LicenseCenter(args.dir or _license_dir())
    led = center.ledger
    act = args.action
    if act == "init":
        if getattr(args, "force", False):
            path = center.dir / "ledger.json"
            if path.exists():
                path.unlink()
            led = licensing.Ledger(center.dir / "ledger.json")
            print("已重建台账（旧码全部作废）")
        print(f"台账：{center.dir / 'ledger.json'}")
        print(f"  secret = {led.data['secret'][:12]}…（完整值在文件里）")
        print(f"  下一个序列号 #{led.data.get('nextSerial', 1)}")
        return 0
    if act == "import":
        src = getattr(args, "src", None)
        if not src:
            print("用法：superlocator license import --from work/license/ledger.json")
            return 2
        other = licensing.Ledger(Path(src))
        data = center.ledger.data
        # 母台账为准：码表/吊销表整体替换，避免两边各留一半
        data["secret"] = other.data["secret"]
        data["codes"] = list(other.data.get("codes", []))
        data["revoked"] = sorted({int(x) for x in other.data.get("revoked", [])})
        data["nextSerial"] = int(other.data.get("nextSerial", 1))
        center.ledger._save()
        print(f"已同步母台账：{src}")
        print(f"  secret = {data['secret'][:12]}…  码 {len(data.get('codes', []))} 个 / 吊销 {len(data.get('revoked', []))} 个")
        return 0

    if act == "keygen":
        if not args.device_hash and args.count < 1:
            print("要么 --device-hash，要么 -n N")
            return 1
        for _ in range(max(1, args.count)):
            item = led.issue(universal=not args.device_hash, dev_hash=args.device_hash, note=args.note)
            print(f"#{item['serial']:<4} {item['code']}   "
                  f"{'通用' if not args.device_hash else '绑定 ' + args.device_hash}")
        return 0
    if act == "list":
        revoked = {int(x) for x in led.data.get("revoked", [])}
        print(f"{'序号':<6}{'状态':<8}{'类型':<10}激活码")
        for c in led.data.get("codes", []):
            ser = int(c["serial"])
            print(f"#{ser:<5}{'已吊销' if ser in revoked else '有效':<8}"
                  f"{'设备绑定' if c.get('device') else '通用':<10}{c['code']}")
        devs = center.state.devices()
        if devs:
            print()
            print("已激活设备：")
            for k, v in devs.items():
                print(f"  {k[:12]}… #{v.get('serial')} @ {v.get('at')}")
        return 0
    if act in ("revoke", "unrevoke"):
        if not args.serial:
            print("要给 --serial")
            return 1
        for ser in args.serial:
            led.revoke(int(ser), on=(act == "revoke"))
            print(("已吊销 #" if act == "revoke" else "已恢复 #") + str(ser))
        return 0
    if act == "delete":
        if not args.serial:
            print("要给 --serial")
            return 1
        for ser in args.serial:
            led.delete(int(ser))
            print(f"已从台账删除 #{ser}")
        return 0
    if act == "verify":
        if not args.code:
            print("要给 --code")
            return 1
        res = led.verify(args.code, args.device_hash)
        print(("通过" if res["ok"] else "不通过") + f" · #{res.get('serial', 0)} · {res.get('message', '')}")
        return 0 if res["ok"] else 2
    if act == "devices":
        devs = center.state.devices()
        print("已激活设备：" if devs else "还没有设备激活")
        for k, v in devs.items():
            print(f"  {k}  #{v.get('serial')} @ {v.get('at')}")
        return 0
    center.deactivate()
    print("已清空本机所有激活记录（设备需重新输入激活码）")
    return 0



def cmd_agent(args) -> int:
    """服务器模式的本机端：把本机 iPhone 的写入能力桥给远端服务器。"""
    token = args.token or os.environ.get("RELAY_TOKEN", "")
    print(f"本机 agent → {args.host}:{args.port}（engine={args.engine}）")
    print("  这个窗口不要关；关掉后服务器就写不进坐标了。")
    backoff = 3.0
    provider = None
    while True:
        try:
            sock = socket.create_connection((args.host, args.port), timeout=15)
        except OSError as exc:
            print(f"[!] 连不上服务器（{exc}），{backoff:.0f} 秒后重试")
            time.sleep(backoff)
            backoff = min(30.0, backoff * 1.6)
            continue
        backoff = 3.0
        sock.settimeout(None)
        f = sock.makefile("rwb")
        try:
            hello = {"op": "hello", "token": token, "version": APP_VERSION, "engine": args.engine}
            f.write((json.dumps(hello) + "\n").encode())
            f.flush()
            res = json.loads(f.readline().decode("utf-8") or "{}")
            if not res.get("ok"):
                print(f"[!] 服务器拒绝连接：{res.get('error')}")
                sock.close()
                return 2
            print("已连上服务器，等待坐标下发…")
            if provider is None:
                provider = make_provider(args.engine, args.udid, args.rsd, args.quiet)
                try:
                    provider.open()
                except Exception as exc:
                    print(f"[!] 本机 iPhone 暂未就绪：{exc}")
                    print("    插好数据线并在手机上点『信任』；收到坐标时自动重试。")
            while True:
                line = f.readline()
                if not line:
                    print("[!] 与服务器断开，重连中…")
                    break
                try:
                    msg = json.loads(line.decode("utf-8"))
                except Exception:
                    continue
                op = msg.get("op")
                if op == "ping":
                    f.write((json.dumps({"ok": True}) + "\n").encode())
                    f.flush()
                    continue
                if op not in ("set", "clear"):
                    f.write((json.dumps({"ok": False, "error": f"未知指令 {op}"}) + "\n").encode())
                    f.flush()
                    continue
                try:
                    if op == "clear":
                        provider.clear()
                    else:
                        provider.set_location(float(msg["lat"]), float(msg["lon"]))
                    f.write((json.dumps({"ok": True}) + "\n").encode())
                    f.flush()
                except Exception as exc:
                    f.write((json.dumps({"ok": False, "error": str(exc)}) + "\n").encode())
                    f.flush()
                    try:
                        provider.open()
                    except Exception:
                        pass
        except OSError:
            pass
        finally:
            try:
                sock.close()
            except Exception:
                pass
        time.sleep(2.0)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="superlocator", description="超级虚拟定位 · iOS 伴侣程序")
    p.add_argument("--version", action="version", version=APP_VERSION)
    p.add_argument("--log-file", dest="log_file", default=None, help="同时把输出写入该文件")
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp):
        sp.add_argument("--engine", choices=["lib", "cli", "dry", "relay"], default="lib")
        sp.add_argument("--udid")
        sp.add_argument("--rsd", help="iOS 17+ 隧道地址 host:port")
        sp.add_argument("--quiet", action="store_true")

    sp = sub.add_parser("list", help="列出已连接的 iOS 设备")
    sp.set_defaults(func=cmd_list)

    sp = sub.add_parser("set", help="设置一次坐标")
    sp.add_argument("--lat", type=float, required=True)
    sp.add_argument("--lon", type=float, required=True)
    common(sp)
    sp.set_defaults(func=cmd_set)

    sp = sub.add_parser("clear", help="清除虚拟位置，回到真实定位")
    common(sp)
    sp.set_defaults(func=cmd_clear)

    sp = sub.add_parser("play", help="按时间轴播放轨迹或预设路径")
    sp.add_argument("--file", required=True)
    sp.add_argument("--kind", choices=["auto", "track", "route"], default="auto",
                    help="auto=按 JSON 里有没有 nodes 判断")
    sp.add_argument("--speed", type=float, default=1.0, help="轨迹播放倍率 0.1~20")
    sp.add_argument("--offset", type=float, default=20.0, help="预设路径每段速度偏移百分比")
    sp.add_argument("--loop", action="store_true")
    sp.add_argument("--radius", type=float, default=0.0, help="抖动半径（米）")
    sp.add_argument("--bias", type=float, default=0.0, help="权重偏于 0~1")
    sp.add_argument("--bearing", type=float, default=None, help="偏向方位角，省略=随机")
    sp.add_argument("--hz", type=float, default=10.0)
    sp.add_argument("--interval", type=float, default=0.0, help="帧间隔（秒），给了就覆盖 --hz")
    common(sp)
    sp.set_defaults(func=cmd_play)

    sp = sub.add_parser("serve", help="开 TCP 服务给 iPhone App 连接")
    sp.add_argument("--host", default="0.0.0.0")
    sp.add_argument("--port", type=int, default=SERVER_PORT)
    sp.add_argument("--http-port", type=int, default=SERVER_PORT + 1,
                    help="网页版端口（0 = 关闭），默认 TCP 端口 +1")
    sp.add_argument("--hz", type=float, default=10.0)
    sp.add_argument("--license-dir", help="授权台账目录（默认程序旁边的 license/）")
    sp.add_argument("--no-license", action="store_true", help="关闭激活校验（自测用）")
    sp.add_argument("--relay-port", type=int, default=RELAY_PORT,
                    help="服务器模式：本地 agent 连进来的端口（engine=relay 时生效）")
    sp.add_argument("--relay-token", default="", help="服务器模式：握手 token（agent 必须一致）")
    common(sp)
    sp.set_defaults(func=cmd_serve)

    sp = sub.add_parser("agent", help="服务器模式：插着 iPhone 的本机跑这个，把写入能力桥给远端")
    sp.add_argument("--host", required=True, help="服务器地址（域名或 IP）")
    sp.add_argument("--port", type=int, default=RELAY_PORT)
    sp.add_argument("--token", default=os.environ.get("RELAY_TOKEN", ""))
    common(sp)
    sp.set_defaults(func=cmd_agent)

    sp = sub.add_parser("license", help="激活码：init/keygen/list/revoke/delete/verify/devices/reset")
    sp.add_argument("action", choices=["init", "import", "keygen", "list", "revoke", "unrevoke",
                                       "delete", "verify", "devices", "reset"])
    sp.add_argument("--device-hash", help="绑定到某台设备（App 激活页显示的 16 位）")
    sp.add_argument("--serial", type=int, nargs="*", help="revoke/unrevoke/delete 用")
    sp.add_argument("--code", help="verify 用")
    sp.add_argument("--note", default="")
    sp.add_argument("-n", "--count", type=int, default=1)
    sp.add_argument("--dir", help="台账目录（默认程序旁边的 license/）")
    sp.add_argument("--force", action="store_true", help="init 时覆盖已有台账（旧码全部作废）")
    sp.add_argument("--from", dest="src", help="import 时的母台账路径（acttool 的 ledger.json）")
    sp.set_defaults(func=cmd_license)

    sp = sub.add_parser("doctor", help="自检：临时目录/台账/引擎/端口（打不开时先跑这个）")
    sp.add_argument("--license-dir")
    sp.set_defaults(func=cmd_doctor)

    sp = sub.add_parser("gpx", help="把轨迹导出成 GPX")
    sp.add_argument("--file", required=True)
    sp.add_argument("--out", required=True)
    sp.set_defaults(func=cmd_gpx)
    return p


def _hold_window() -> None:
    """双击启动时把窗口留住，避免一闪而过看不到原因。"""
    try:
        if sys.stdin is not None and sys.stdin.isatty():
            print("\n按回车键关闭这个窗口 …")
            sys.stdin.readline()
    except Exception:
        pass


def main(argv: Optional[List[str]] = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    if not argv:
        # 双击 exe：直接当“启动服务”，并把日志写在 exe 旁边
        here = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path.cwd()
        argv = ["--log-file", str(here / "superlocator.log"), "serve", "--engine", "lib"]
        print("== 超级虚拟定位 · 电脑端伴侣程序 ==")
        print("没有参数：按「启动服务」处理。这个窗口不要关，关了服务就停。")
    try:
        args = build_parser().parse_args(argv)
    except SystemExit:
        raise
    if getattr(args, "log_file", None):
        try:
            fh = open(args.log_file, "a", encoding="utf-8", buffering=1)
            sys.stdout = _Tee(sys.stdout, fh)
            sys.stderr = _Tee(sys.stderr, fh)
        except Exception as exc:
            print(f"[!] log file unavailable {args.log_file}: {exc}")
    try:
        return args.func(args)
    except KeyboardInterrupt:
        return 0
    except Exception:
        import traceback
        print("\n[!] 运行出错，下面是完整原因：")
        traceback.print_exc()
        print("\n排查：双击 doctor.bat 做自检；或把 superlocator.log 全文发给开发者。")
        _hold_window()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())