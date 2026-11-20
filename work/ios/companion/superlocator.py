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
import http.server
import json
import math
import os
import random
import socket
import socketserver
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Tuple

from webapp_page import PAGE

APP_VERSION = "1.0.0"
DEFAULT_INTERVAL_MS = 100
SERVER_PORT = 47654

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


class CliProvider(BaseProvider):
    """最稳的通道：每次调用 pymobiledevice3 命令行（速率建议 ≤ 2Hz）。"""

    name = "cli"

    def __init__(self, udid: Optional[str] = None, rsd: Optional[str] = None, verbose: bool = False):
        self.udid = udid
        self.rsd = rsd
        self.verbose = verbose

    def _base(self) -> List[str]:
        cmd = [sys.executable, "-m", "pymobiledevice3"]
        if self.rsd:
            cmd += ["--rsd", self.rsd]
        elif self.udid:
            cmd += ["--udid", self.udid]
        return cmd + ["developer", "dvt", "simulate-location"]

    def set_location(self, lat: float, lon: float) -> None:
        cmd = self._base() + ["set", "--latitude", f"{lat:.7f}", "--longitude", f"{lon:.7f}"]
        if self.verbose:
            print(" ".join(cmd), flush=True)
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError((r.stderr or r.stdout).strip()[:300])

    def clear(self) -> None:
        subprocess.run(self._base() + ["clear"], capture_output=True, text=True)


class LibProvider(BaseProvider):
    """常驻 DVT 会话（10Hz 无压力）。pymobiledevice3 需要 ≥ 4.x。"""

    name = "lib"

    def __init__(self, udid: Optional[str] = None, verbose: bool = False):
        self.udid = udid
        self.verbose = verbose
        self._dvt = None
        self._loc = None

    def open(self) -> None:
        from pymobiledevice3.lockdown import create_using_usbmux          # type: ignore
        from pymobiledevice3.services.dvt.instruments.dvt_provider import DvtProvider  # type: ignore
        from pymobiledevice3.services.dvt.instruments.location_simulation import LocationSimulation  # type: ignore

        lockdown = create_using_usbmux(serial=self.udid) if self.udid else create_using_usbmux()
        self._dvt = DvtProvider(lockdown)
        self._dvt.__enter__()
        self._loc = LocationSimulation(self._dvt)

    def set_location(self, lat: float, lon: float) -> None:
        if self._loc is None:
            self.open()
        self._loc.set(lat, lon)     # type: ignore[union-attr]

    def clear(self) -> None:
        if self._loc is not None:
            try:
                self._loc.clear()   # type: ignore[union-attr]
            except Exception:
                pass

    def close(self) -> None:
        try:
            if self._dvt is not None:
                self._dvt.__exit__(None, None, None)
        except Exception:
            pass


def make_provider(engine: str, udid: Optional[str], rsd: Optional[str], quiet: bool) -> BaseProvider:
    if engine == "lib":
        return LibProvider(udid=udid, verbose=not quiet)
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
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            print(f"[serve] 客户端断开 {peer}", flush=True)
            srv.player.on_tick = None

    @staticmethod
    def _line(obj: Dict[str, Any]) -> bytes:
        return (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8")


class BridgeServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, addr, player: Player, device_name: str = ""):
        super().__init__(addr, _Handler)
        self.bridge = self
        self.player = player
        self.device_name = device_name

    def handle(self, msg: Dict[str, Any]) -> Dict[str, Any]:
        cmd = str(msg.get("cmd", "")).lower()
        try:
            if cmd in ("ping", "hello"):
                return {"ok": True, "cmd": cmd, "version": APP_VERSION}
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
        if path == "/api/status":
            self._json({"ok": True, **bridge.player._snapshot(),          # noqa: SLF001
                        "running": bridge.player.is_running()})
            return
        if path == "/favicon.ico":
            self._send(b"", "image/x-icon", 204)
            return
        self._json({"ok": False, "error": "not found"}, 404)

    def do_POST(self) -> None:
        path = self.path.split("?", 1)[0]
        bridge = self.server.bridge            # type: ignore[attr-defined]
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
    allow_reuse_address = True
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
    provider.open()
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


def cmd_serve(args) -> int:
    provider = make_provider(args.engine, args.udid, args.rsd, args.quiet)
    provider.open()
    player = Player(provider, hz=args.hz)
    srv = BridgeServer((args.host, args.port), player, device_name=args.udid or "")
    print(f"监听 {args.host}:{args.port}（engine={provider.name}），在 iPhone App 里填这个地址")
    if args.http_port:
        web = WebBridge((args.host, args.http_port), srv)
        threading.Thread(target=web.serve_forever, daemon=True).start()
        print(f"网页版（iPhone Safari 直接打开，不用装任何东西）：http://{_lan_ip()}:{args.http_port}/")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n退出")
    finally:
        player.stop()
        srv.server_close()
    return 0


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


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="superlocator", description="超级虚拟定位 · iOS 伴侣程序")
    p.add_argument("--version", action="version", version=APP_VERSION)
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp):
        sp.add_argument("--engine", choices=["lib", "cli", "dry"], default="lib")
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
    common(sp)
    sp.set_defaults(func=cmd_serve)

    sp = sub.add_parser("gpx", help="把轨迹导出成 GPX")
    sp.add_argument("--file", required=True)
    sp.add_argument("--out", required=True)
    sp.set_defaults(func=cmd_gpx)
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())