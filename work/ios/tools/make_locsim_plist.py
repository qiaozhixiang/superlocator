# -*- coding: utf-8 -*-
"""把轨迹 JSON / 预设路径 JSON 转成 LocSim 越狱插件的配置文件（plist）。

支持三种输入：
1. 轨迹（本工程 Track 格式）：{"points": [[t, lat, lng], ...], "intervalMs": 500, ...}
2. 预设路径（PresetRoute）：{"nodes": [{"lat":..,"lng":..,"speedMps":..}, ...], "globalSpeed": 1.4, ...}
3. 纯坐标数组：[{"lat":..,"lng":..}, ...]

用法：
    python tools/make_locsim_plist.py companion/samples/route_campus.json -o jailbreak/com.stv.locsim.plist
    python tools/make_locsim_plist.py track.json --radius 20 --bias 0.55 --bearing 90 --loop
"""
import argparse
import json
import plistlib
import sys



def _node(n, default_speed=0.0):
    if isinstance(n, dict):
        s = float(n.get("speedMps", n.get("speed", 0)) or 0)
        return {"lat": float(n["lat"]), "lng": float(n["lng"]), "speed": s if s > 0 else default_speed}
    # [lat, lng] 或 [lat, lng, speed]
    s = float(n[2]) if len(n) > 2 and n[2] else 0.0
    return {"lat": float(n[0]), "lng": float(n[1]), "speed": s if s > 0 else default_speed}


def load_nodes(path):
    with open(path, encoding="utf-8") as f:
        d = json.load(f)

    if isinstance(d, list):
        return [_node(p) for p in d]

    if "nodes" in d:                                     # PresetRoute
        default = float(d.get("globalSpeed", 1.4) or 1.4)
        return [_node(n, default) for n in d["nodes"]]

    if "points" in d:                                    # Track
        pts = d["points"]
        out = []
        for i, p in enumerate(pts):
            if isinstance(p, dict):
                out.append({"lat": float(p["lat"]), "lng": float(p["lng"]), "speed": 0.0})
                continue
            t, lat, lng = float(p[0]), float(p[1]), float(p[2])
            speed = 0.0
            if i + 1 < len(pts):
                q = pts[i + 1]
                t2, lat2, lng2 = float(q[0]), float(q[1]), float(q[2])
                dt = max(0.001, (t2 - t) / 1000.0)
                speed = max(0.2, min(25.0, haversine(lat, lng, lat2, lng2) / dt))
            out.append({"lat": lat, "lng": lng, "speed": round(speed, 3)})
        return out

    raise SystemExit("看不懂这个 JSON：既没有 nodes 也没有 points")


def haversine(lat1, lng1, lat2, lng2):
    from math import radians, sin, cos, atan2, sqrt
    r = 6371008.8
    p1, p2 = radians(lat1), radians(lat2)
    dp, dl = p2 - p1, radians(lng2 - lng1)
    a = sin(dp / 2) ** 2 + cos(p1) * cos(p2) * sin(dl / 2) ** 2
    return 2 * r * atan2(sqrt(a), sqrt(1 - a))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("-o", "--out", default="jailbreak/com.stv.locsim.plist")
    ap.add_argument("--radius", type=float, default=0.0, help="抖动半径（米），0=不抖")
    ap.add_argument("--bias", type=float, default=0.0, help="偏向权重 0..1")
    ap.add_argument("--bearing", type=float, default=None, help="偏向方位角（度），不填=随机")
    ap.add_argument("--loop", action="store_true")
    ap.add_argument("--off", action="store_true", help="生成但 enabled=false")
    a = ap.parse_args()

    nodes = load_nodes(a.input)
    cfg = {
        "enabled": not a.off,
        "lat": nodes[0]["lat"],
        "lng": nodes[0]["lng"],
        "radius": a.radius,
        "biasWeight": max(0.0, min(1.0, a.bias)),
        "biasBearing": (a.bearing if a.bearing is not None else float("nan")),
        "loop": bool(a.loop),
        "route": nodes,
    }
    with open(a.out, "wb") as f:
        plistlib.dump(cfg, f, fmt=plistlib.FMT_XML, sort_keys=False)
    print(f"{a.out}: {len(nodes)} 个节点，enabled={cfg['enabled']}，radius={a.radius}，"
          f"bias={cfg['biasWeight']}，bearing={cfg['biasBearing']}")
    print("拷到手机： /var/mobile/Library/Preferences/com.stv.locsim.plist")
    print("生效： killall -HUP backboardd  或 发通知 com.stv.locsim.reload")


if __name__ == "__main__":
    sys.exit(main())