#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""superlocator 自检：不依赖 iPhone，验证几何、抖动、预设路径速度区间与 TCP 协议。"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import superlocator as sl  # noqa: E402


class TestGeo(unittest.TestCase):
    def test_distance_known(self):
        # 济南 → 泰安 约 62km
        d = sl.Geo.distance(36.667662, 117.027707, 36.200000, 117.080000)
        self.assertTrue(50_000 < d < 75_000, d)

    def test_offset_roundtrip(self):
        lat, lon = sl.Geo.offset(36.71, 117.02, 100.0, 0.0)
        back = sl.Geo.distance(36.71, 117.02, lat, lon)
        self.assertAlmostEqual(back, 100.0, delta=1.0)

    def test_point_along_endpoints(self):
        a = sl.Geo.point_along(36.7, 117.0, 36.8, 117.1, 0.0)
        b = sl.Geo.point_along(36.7, 117.0, 36.8, 117.1, 1.0)
        self.assertAlmostEqual(a[0], 36.7, places=6)
        # 平面近似（每度 111132.92 米）在 13km 尺度上有 ~0.0001° 误差，属预期
        self.assertAlmostEqual(b[0], 36.8, places=3)


class TestJitter(unittest.TestCase):
    def test_zero_radius_no_offset(self):
        j = sl.Jitter(0, 0.5, 90)
        self.assertEqual(j.step(0), (0.0, 0.0))
        self.assertEqual(j.step(1000), (0.0, 0.0))

    def test_bounded(self):
        j = sl.Jitter(20, 0.55, 90, seed=7)
        for i in range(1, 400):
            east, north = j.step(i * 100.0)
            self.assertLessEqual((east ** 2 + north ** 2) ** 0.5, 30.0 + 1e-6)

    def test_bias_direction_is_roughly_toward_bearing(self):
        j = sl.Jitter(20, 0.9, 90.0, seed=11)     # 90° = 正东
        east_sum = 0.0
        for i in range(1, 800):
            east, north = j.step(i * 100.0)
            east_sum += east
        self.assertGreater(east_sum, 0.0)          # 强偏向正东 → 东向偏移为正


class TestRouteSpeed(unittest.TestCase):
    def test_segment_speed_range(self):
        route = sl.PresetRoute(nodes=[
            sl.RouteNode(36.7102, 117.0215, 0.0),
            sl.RouteNode(36.7104, 117.0219, 2.0),    # 该段 2.0 m/s
            sl.RouteNode(36.7106, 117.0224, 0.0),
        ], globalSpeed=1.4, offsetPercent=30.0)
        p = sl.Player(sl.DryProvider(verbose=False))
        p.load_route(route, offset_percent=30.0)
        # 段 0 由节点 0 的速度决定（0 → 跟随全局 1.4），段 1 由节点 1 决定（2.0）
        self.assertEqual(route.base_speed(0), 1.4)
        self.assertEqual(route.base_speed(1), 2.0)
        # 每段速度偏移 ±30% 采样 200 次，全部落在区间内
        import random
        random.seed(3)
        for _ in range(200):
            factor = 1.0 + (random.random() * 2 - 1) * 0.30
            s0 = max(0.2, min(25.0, route.base_speed(0) * factor))
            s1 = max(0.2, min(25.0, route.base_speed(1) * factor))
            self.assertTrue(1.4 * 0.7 <= s0 <= 1.4 * 1.3)
            self.assertTrue(2.0 * 0.7 <= s1 <= 2.0 * 1.3)

    def test_total_length(self):
        route = sl.PresetRoute(nodes=[
            sl.RouteNode(36.7102, 117.0215, 0.0),
            sl.RouteNode(36.7104, 117.0219, 0.0),
        ], globalSpeed=1.4)
        self.assertGreater(route.segment_lengths()[0], 10.0)


class LineClient:
    """行分隔 JSON 客户端：socket 对象有 __slots__，不能挂 buf，故包一层。"""

    def __init__(self, sock):
        self.sock = sock
        self.buf = b""

    def send(self, obj):
        self.sock.sendall((json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8"))

    def recv(self):
        while b"\n" not in self.buf:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise EOFError("connection closed")
            self.buf += chunk
        line, self.buf = self.buf.split(b"\n", 1)
        return json.loads(line.decode("utf-8"))

    def close(self):
        self.sock.close()


class TestBridgeProtocol(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.proc = subprocess.Popen(
            [sys.executable, "superlocator.py", "serve", "--engine", "dry",
             "--quiet", "--host", "127.0.0.1", "--port", "47699"],
            cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        time.sleep(1.2)

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        try:
            cls.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            cls.proc.kill()

    def _conn(self):
        s = socket.create_connection(("127.0.0.1", 47699), timeout=5)
        s.settimeout(5)
        return LineClient(s)

    @staticmethod
    def _expect(client, cmd, limit=40):
        """跳过推送的 position 事件，拿到指定命令的回执。"""
        for _ in range(limit):
            msg = client.recv()
            if msg.get("cmd") == cmd and "ok" in msg:
                return msg
        raise AssertionError(f"没有等到 {cmd} 的回执")

    def test_hello_play_pause_stop(self):
        c = self._conn()
        hello = c.recv()
        self.assertTrue(hello["ok"])
        self.assertEqual(hello["event"], "hello")

        track = json.load(open(os.path.join(ROOT, "samples", "track_campus.json"), encoding="utf-8"))
        track["speed"] = 4.0
        track["radius"] = 15.0
        track["bias"] = 0.5
        c.send({"cmd": "play", "payload": track})
        replies = []
        deadline = time.time() + 6
        seen_position = False
        while time.time() < deadline:
            msg = c.recv()
            replies.append(msg)
            if msg.get("event") == "position":
                seen_position = True
                self.assertIn("lat", msg)
                break
        self.assertTrue(seen_position, replies[-3:])

        c.send({"cmd": "pause"})
        self.assertTrue(self._expect(c, "pause")["ok"])
        c.send({"cmd": "status"})
        st = self._expect(c, "status")
        self.assertIn("running", st)
        c.send({"cmd": "stop"})
        self.assertTrue(self._expect(c, "stop")["ok"])
        c.close()

    def test_unknown_cmd(self):
        c = self._conn()
        c.recv()
        c.send({"cmd": "say_hi"})
        r = c.recv()
        self.assertFalse(r["ok"])
        c.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)