#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 Swift 单元测试用的黄金向量（golden.json）

同一套公式在 Python 伴侣程序里已经跑过自检，把结果固化成向量，
让 Xcode 里的 XCTest 直接对照 —— 这样 iOS App 的几何/插值实现被证实与
Android 版、伴侣程序三方一致（误差 < 1e-9）。

用法：
  python work/ios/tools/make_golden.py                 # 写到 SuperLocator/Tests/golden.json
  python work/ios/tools/make_golden.py --out /tmp/g.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "companion"))

from superlocator import Geo, Player, Track, TrackPoint  # noqa: E402

PAIRS = [
    (36.710210, 117.021550, 36.711210, 117.022550),
    (36.667662, 117.027707, 36.672000, 117.033000),
    (39.908722, 116.397499, 39.900000, 116.410000),
    (-33.868820, 151.209290, -33.870000, 151.211000),
    (36.710210, 117.021550, 36.710210, 117.021550),   # 同点
]

OFFSETS = [
    (36.710210, 117.021550, 0.0, 0.0),
    (36.710210, 117.021550, 100.0, 0.0),
    (36.710210, 117.021550, 0.0, 100.0),
    (36.710210, 117.021550, -50.0, 25.0),
    (61.000000, 25.000000, 30.0, -40.0),              # 高纬 cos 收缩
]

FRACTIONS = [0.0, 0.25, 0.5, 0.75, 1.0]

TRACK_POINTS = [
    (0, 36.710210, 117.021550),
    (1000, 36.711210, 117.022550),
    (2000, 36.712000, 117.023800),
    (3000, 36.712800, 117.024900),
    (4000, 36.713500, 117.026000),
]


def build() -> dict:
    out: dict = {
        "generatedBy": "work/ios/tools/make_golden.py",
        "note": "WGS-84；值与伴侣程序 superlocator.py 的 Geo/Player 输出一致",
        "distance": [],
        "bearing": [],
        "offset": [],
        "pointAlong": [],
        "interpolate": {"points": [list(p) for p in TRACK_POINTS], "cases": []},
    }

    for lat1, lng1, lat2, lng2 in PAIRS:
        out["distance"].append({
            "lat1": lat1, "lng1": lng1, "lat2": lat2, "lng2": lng2,
            "meters": Geo.distance(lat1, lng1, lat2, lng2),
        })
        out["bearing"].append({
            "lat1": lat1, "lng1": lng1, "lat2": lat2, "lng2": lng2,
            "deg": Geo.bearing(lat1, lng1, lat2, lng2),
        })

    for lat, lng, east, north in OFFSETS:
        la, ln = Geo.offset(lat, lng, east, north)
        out["offset"].append({
            "lat": lat, "lng": lng, "east": east, "north": north,
            "outLat": la, "outLng": ln,
        })

    for lat1, lng1, lat2, lng2 in PAIRS[:4]:
        for f in FRACTIONS:
            la, ln = Geo.point_along(lat1, lng1, lat2, lng2, f)
            out["pointAlong"].append({
                "lat1": lat1, "lng1": lng1, "lat2": lat2, "lng2": lng2,
                "fraction": f, "outLat": la, "outLng": ln,
            })

    track = Track.from_json({
        "id": "golden", "name": "golden", "intervalMs": 1000,
        "points": [list(p) for p in TRACK_POINTS],
    })
    player = Player(provider=None, hz=10.0)          # 只借它的 _position_at
    player._track = track                           # noqa: SLF001
    for ms in (-500, 0, 250, 500, 900, 1000, 1500, 2000, 2600, 3000, 3500, 4000, 4500):
        la, ln = player._position_at(float(ms))     # noqa: SLF001
        out["interpolate"]["cases"].append({"ms": ms, "outLat": la, "outLng": ln})

    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path,
                    default=ROOT / "SuperLocator" / "Tests" / "golden.json")
    args = ap.parse_args()
    data = build()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    n = sum(len(v) for v in data.values() if isinstance(v, list)) + len(data["interpolate"]["cases"])
    print(f"已写出 {args.out}（{n} 条向量）")
    return 0


if __name__ == "__main__":
    sys.exit(main())