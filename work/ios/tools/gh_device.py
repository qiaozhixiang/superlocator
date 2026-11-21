# -*- coding: utf-8 -*-
"""GitHub 设备码登录（不需要提前有 token，也不用输密码给我）：

1. 脚本向 GitHub 申请一个 8 位设备码；
2. 你在浏览器打开 https://github.com/login/device 输入它并点授权；
3. 脚本轮询到 access_token 后写到 .publish/gh_token.txt（本机文件，权限 600）。

用法：
    python tools/gh_device.py            # 申请 + 等待授权（前台，最长 15 分钟）
    python tools/gh_device.py --show     # 只看已有的 token 是否可用
"""
import json
import os
import sys
import time
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOKEN_FILE = os.path.join(ROOT, ".publish", "gh_token.txt")
CLIENT_ID = "178c6fc778ccc68e1d6a"          # GitHub CLI 的公开 OAuth client id
SCOPE = "repo workflow read:org"


def _post(url, data, accept="application/json"):
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=body, headers={
        "Accept": accept,
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": "SuperLocator-DeviceFlow/1.0",
    })
    with urllib.request.urlopen(req, timeout=30) as f:
        return json.loads(f.read().decode("utf-8"))


def _get(url, token):
    req = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "Authorization": "Bearer " + token,
        "User-Agent": "SuperLocator-DeviceFlow/1.0",
    })
    with urllib.request.urlopen(req, timeout=30) as f:
        return json.loads(f.read().decode("utf-8"))


def login():
    start = _post("https://github.com/login/device/code",
                  {"client_id": CLIENT_ID, "scope": SCOPE})
    code = start["user_code"]
    uri = start.get("verification_uri", "https://github.com/login/device")
    interval = int(start.get("interval", 5))
    deadline = time.time() + int(start.get("expires_in", 900)) - 5

    print("=" * 58)
    print("  打开： " + uri)
    print("  输入： " + code)
    print("  点「Authorize」后不用关窗口，这里会自动继续。")
    print("=" * 58)
    sys.stdout.flush()

    while time.time() < deadline:
        time.sleep(interval)
        try:
            r = _post("https://github.com/login/oauth/access_token", {
                "client_id": CLIENT_ID,
                "device_code": start["device_code"],
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            })
        except Exception as e:              # 网络抖动重试
            print("poll error:", e)
            continue
        err = r.get("error")
        if err == "authorization_pending":
            continue
        if err == "slow_down":
            interval += 5
            continue
        if err:
            print("授权失败:", err, r.get("error_description", ""))
            return 2
        token = r.get("access_token")
        if not token:
            continue
        os.makedirs(os.path.dirname(TOKEN_FILE), exist_ok=True)
        with open(TOKEN_FILE, "w", encoding="utf-8") as f:
            f.write(token)
        try:
            os.chmod(TOKEN_FILE, 0o600)
        except Exception:
            pass
        me = _get("https://api.github.com/user", token)
        print("OK: 已授权账号", me.get("login"), "/ token 写入", TOKEN_FILE)
        return 0
    print("超时：设备码 15 分钟过期，重跑本脚本即可。")
    return 3


def show():
    if not os.path.exists(TOKEN_FILE):
        print("还没有 token")
        return 1
    token = open(TOKEN_FILE, encoding="utf-8").read().strip()
    me = _get("https://api.github.com/user", token)
    print("token 有效，账号 =", me.get("login"))
    return 0


if __name__ == "__main__":
    sys.exit(show() if "--show" in sys.argv else login())