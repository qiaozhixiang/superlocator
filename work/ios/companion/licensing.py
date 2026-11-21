# -*- coding: utf-8 -*-
"""伴侣程序侧的激活码（授权中心）。

算法与 APK 的 CodeMath.java、work/tools/license_core.py 逐位一致：
    payload = serial(10 bit) | mac(90 bit) → 20 个 Crockford-Base32 字符（4 组 × 5）
    mac     = HMAC-SHA256(secret, scope || serial_be16)[:12] 取前 90 bit
    scope   = "D" + deviceHash（设备绑定码）或 "U"（通用码）

与 Android 不同的是：iOS 这边**密钥只留在电脑**，手机不保管 secret。
App / 网页版把激活码发给本程序校验，校验通过才存在本地状态里（可随时吊销）。
"""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
from pathlib import Path

ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
SERIAL_BITS = 10
MAC_BITS = 90
CODE_BITS = 100
MAX_SERIAL = 1023
SCHEMA = 1


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def make_code(secret_hex: str, serial: int, dev_hash: str | None = None) -> str:
    if not (1 <= serial <= MAX_SERIAL):
        raise ValueError(f"serial 必须在 1..{MAX_SERIAL}")
    scope = (b"D" + dev_hash.encode()) if dev_hash else b"U"
    mac = hmac.new(bytes.fromhex(secret_hex), scope + serial.to_bytes(2, "big"), hashlib.sha256).digest()[:12]
    mac90 = int.from_bytes(mac, "big") >> (96 - MAC_BITS)
    value = (serial << MAC_BITS) | mac90
    body = "".join(ALPHABET[(value >> (5 * i)) & 0x1F] for i in range(CODE_BITS // 5 - 1, -1, -1))
    return "-".join(body[i:i + 5] for i in range(0, 20, 5))


def decode(code: str) -> tuple[int, int]:
    clean = (code or "").replace("-", "").replace(" ", "").strip().upper()
    if len(clean) != 20:
        raise ValueError(f"长度不对：需要 20 位（收到 {len(clean)}）")
    n = 0
    for i, ch in enumerate(clean):
        idx = ALPHABET.find(ch)
        if idx < 0:
            raise ValueError(f"第 {i + 1} 位字符无效（I L O U 不可用）")
        n = (n << 5) | idx
    return (n >> MAC_BITS) & ((1 << SERIAL_BITS) - 1), n & ((1 << MAC_BITS) - 1)


def device_hash(seed: str) -> str:
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]


class Ledger:
    """授权台账：codes（码）、revoked（吊销）、secret（根密钥）。"""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.data = self._load()

    def _load(self) -> dict:
        if self.path.exists():
            return json.loads(self.path.read_text(encoding="utf-8"))
        data = {
            "schema": SCHEMA,
            "secret": secrets.token_hex(32),
            "createdAt": _now(),
            "nextSerial": 1,
            "codes": [],
            "revoked": [],
            "activations": [],
        }
        self._save(data)
        return data

    def _save(self, data: dict | None = None) -> None:
        if data is not None:
            self.data = data
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")

    # -- 码 ---------------------------------------------------------------
    def issue(self, universal: bool = True, dev_hash: str | None = None, note: str = "") -> dict:
        serial = int(self.data.get("nextSerial", 1))
        if serial > MAX_SERIAL:
            raise ValueError(f"序列号用完了（上限 {MAX_SERIAL}），换一份台账")
        if not universal and not dev_hash:
            raise ValueError("设备绑定码要给 devHash")
        code = make_code(self.data["secret"], serial, None if universal else dev_hash)
        item = {
            "serial": serial,
            "code": code,
            "device": None if universal else dev_hash,
            "note": note or ("通用码" if universal else "设备绑定码"),
            "createdAt": _now(),
        }
        self.data.setdefault("codes", []).append(item)
        self.data["nextSerial"] = serial + 1
        self._save()
        return item

    def revoke(self, serial: int, on: bool = True) -> None:
        rev = {int(x) for x in self.data.get("revoked", [])}
        rev = (rev | {serial}) if on else (rev - {serial})
        self.data["revoked"] = sorted(rev)
        self._save()

    def delete(self, serial: int) -> None:
        self.data["codes"] = [c for c in self.data.get("codes", []) if int(c["serial"]) != serial]
        self._save()

    def refresh(self) -> None:
        """台账被另一个进程（CLI）改过就重读：吊销 / 删除要即时生效。"""
        try:
            mt = self.path.stat().st_mtime
        except OSError:
            return
        if getattr(self, "_mtime", None) != mt:
            self._mtime = mt
            try:
                self.data = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                pass

    def find(self, serial: int) -> dict | None:
        self.refresh()
        for c in self.data.get("codes", []):
            if int(c["serial"]) == serial:
                return c
        return None

    # -- 校验 -------------------------------------------------------------
    def verify(self, code: str, dev_hash: str | None = None) -> dict:
        try:
            serial, given = decode(code)
        except ValueError as exc:
            return {"ok": False, "serial": 0, "message": str(exc)}
        if not (1 <= serial <= MAX_SERIAL):
            return {"ok": False, "serial": serial, "message": "序列号非法"}
        if serial in {int(x) for x in self.data.get("revoked", [])}:
            return {"ok": False, "serial": serial, "message": f"该序列号已被吊销（#{serial}）"}
        item = self.find(serial)
        if item is None:
            return {"ok": False, "serial": serial, "message": f"台账里没有 #{serial}，属于别处发的码"}
        scopes = [(None, "通用码")]
        if dev_hash:
            scopes.append((dev_hash, "设备绑定码"))
        for dev, kind in scopes:
            cand = make_code(self.data["secret"], serial, dev)
            if decode(cand)[1] == given:
                return {"ok": True, "serial": serial,
                        "message": f"通过（{kind} #{serial}）", "kind": kind}
        return {"ok": False, "serial": serial, "message": "码与台账不匹配（被改过或被绑定到别的设备）"}

    # -- 激活记录（哪台设备用了哪个码）---------------------------------
    def activate(self, code: str, dev_hash: str | None = None, client: str = "") -> dict:
        res = self.verify(code, dev_hash)
        if res["ok"]:
            acts = self.data.setdefault("activations", [])
            acts.append({
                "serial": res["serial"],
                "device": dev_hash or "",
                "client": client,
                "at": _now(),
            })
            self._save()
        return res

    def activations(self) -> list:
        return self.data.get("activations", [])


class State:
    """伴侣程序本地的「已激活」状态（每台手机一条，可用 activate/deactivate 增删）。"""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.data = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {"devices": {}}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")

    def record(self, dev_id: str, serial: int, code: str, dev_hash: str = "") -> None:
        self.data.setdefault("devices", {})[dev_id] = {
            "serial": serial, "code": code, "devHash": dev_hash, "at": _now(),
        }
        self._save()

    def get(self, dev_id: str) -> dict:
        return self.data.get("devices", {}).get(dev_id, {})

    def drop(self, dev_id: str | None = None) -> None:
        if dev_id:
            self.data.get("devices", {}).pop(dev_id, None)
        else:
            self.data["devices"] = {}
        self._save()

    def devices(self) -> dict:
        return self.data.get("devices", {})