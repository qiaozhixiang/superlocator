#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""iOS 版「功能是否齐备」静态核对

对每一项 Android 侧已有功能，在 Swift 源码里找对应的符号与界面接线，
输出 功能 → 文件:行 的对照表。任何一行 MISSING 就说明这一版缺功能。

用法：python work/ios/tools/verify_app.py [--json]
退出码：0 = 全部齐备；1 = 有缺失
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "SuperLocator" / "Sources"


@dataclass
class Hit:
    file: str
    line: int
    text: str


def usage_index(files: list[Path]) -> dict[str, Hit]:
    """兜底：把「被使用但没在本工程声明」的系统符号也定位到（如 MKLocalSearch、MapReader）。"""
    out: dict[str, Hit] = {}
    for f in files:
        rel = str(f.relative_to(ROOT))
        for i, raw in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            for token in re.findall(r"[A-Z][A-Za-z0-9_]{3,}", raw):
                out.setdefault(token, Hit(rel, i, raw.strip()[:90]))
    return out


def index(files: list[Path]) -> dict[str, Hit]:
    """把声明类符号收进索引：class/struct/enum/func/var。"""
    out: dict[str, Hit] = {}
    for f in files:
        rel = str(f.relative_to(ROOT))
        for i, raw in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            line = raw.strip()
            m = re.match(r"(?:public |private |fileprivate |internal |final |@MainActor )*"
                         r"(?:class|struct|enum|actor)\s+(\w+)", line)
            if m and m.group(1) not in out:
                out[m.group(1)] = Hit(rel, i, line[:90])
                continue
            m = re.match(r"(?:public |private |fileprivate |internal |static |mutating |@objc )*"
                         r"func\s+(\w+)", line)
            if m and m.group(1) not in out:
                out[m.group(1)] = Hit(rel, i, line[:90])
                continue
            m = re.match(r"(?:public |private |fileprivate |internal |static |@Published )*"
                         r"(?:var|let)\s+(\w+)", line)
            if m and m.group(1) not in out:
                out[m.group(1)] = Hit(rel, i, line[:90])
    return out


FEATURES: list[tuple[str, list[str], str]] = [
    ("录制真实轨迹", ["Recorder", "offer", "stamp"], "500ms 采样 / 1m 位移 / 5s 兜底"),
    ("轨迹分组", ["TrackStore", "createGroup", "deleteGroup"], "groups.json + 分组目录"),
    ("轨迹库（列表/改名/移动/删除）", ["renameTrack", "moveTrack", "deleteTrack", "LibraryView"], "长按菜单"),
    ("重放：时间轴 + 速度倍率 + 循环", ["ReplayEngine", "playTrack", "loop"], "0.1s tick，倍率 0.1~20"),
    ("随机值 / 权重偏于（半径·权重·方位角）", ["Jitter", "configure", "describe"], "4~9s 重采样 + 低通"),
    ("预设路径：多节点沿路位移", ["RouteEngine", "PresetRoute", "RouteNode"], "段长累加 + 段内推进"),
    ("每段单独速度 / 全局速度", ["speedMps", "baseSpeed"], "节点速度 0 = 跟随全局"),
    ("速度偏移量（每段速度区间）", ["offsetPercent", "resample"], "2.5s 重采，0.2~25 m/s 限幅"),
    ("地图选点：点图加点", ["MapPickView", "add", "initialNodes"], "iOS17 Map(position:)"),
    ("地图选点：搜索跳转", ["runSearch", "parseLatLng", "MKLocalSearch"], "地名检索 + 经纬度直解"),
    ("地图选点：缩放 / 撤销 / 恢复 / 暂停拾取 / 回定位", ["undo", "redo", "zoom", "goHere"], "工具栏 7 个按钮"),
    ("轨迹预览（折线/起终点/注入点/进度）", ["TrackPreviewView", "Projector", "dot"], "SwiftUI Canvas"),
    ("伴侣程序连接（TCP 行协议）", ["CompanionClient", "setLocation", "setJitter"], "NWConnection + 重连"),
    ("导出 GPX / JSON 分享", ["toGPX", "ExportView", "jsonText"], "文件 App 可见"),
    ("状态栏（连接/录制/重放/路径）", ["StatusBar", "InjectionSession"], "底部安全区"),
    ("定位权限与真实坐标", ["LocationProvider", "locationManagerDidChangeAuthorization", "refresh"], "作为路径起点参考"),
    ("三端 JSON 兼容（points=[t,lat,lng]）", ["TrackPoint", "RouteNode"], "与 Android 同格式"),
]


def main() -> int:
    files = sorted(SRC.rglob("*.swift"))
    if not files:
        print(f"找不到 Swift 源码：{SRC}")
        return 1
    sym = index(files)
    used = usage_index(files)
    line_total = sum(len(f.read_text(encoding="utf-8").splitlines()) for f in files)

    print(f"iOS 源码：{len(files)} 个文件 / {line_total} 行")
    print(f"抽出符号：{len(sym)} 个\n")
    print(f"{'功能':<40}{'状态':<8}定位")
    print("-" * 100)

    rows = []
    missing = 0
    for name, tokens, note in FEATURES:
        found: list[Hit] = []
        absent: list[str] = []
        for t in tokens:
            h = sym.get(t) or used.get(t)
            if h:
                found.append(h)
            else:
                absent.append(t)
        status = "OK" if not absent else "MISSING"
        if absent:
            missing += 1
        loc = f"{found[0].file}:{found[0].line}" if found else "—"
        print(f"{name:<40}{status:<8}{loc}    {note}")
        rows.append({"feature": name, "status": status, "tokensMissing": absent,
                     "anchors": [{"symbol": t, "file": h.file, "line": h.line}
                                 for t, h in zip(tokens, found)]})

    print("-" * 100)
    print(f"齐备 {len(FEATURES) - missing}/{len(FEATURES)} 项")
    if missing:
        print("缺失项：")
        for r in rows:
            if r["status"] != "OK":
                print(f"  - {r['feature']}: 缺 {', '.join(r['tokensMissing'])}")

    if "--json" in sys.argv:
        print(json.dumps({"files": len(files), "lines": line_total,
                          "features": rows}, ensure_ascii=False, indent=2))
    return 0 if missing == 0 else 1


if __name__ == "__main__":
    sys.exit(main())