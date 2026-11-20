# -*- coding: utf-8 -*-
"""把 iOS 工程推上 GitHub，让 Actions 编出 ipa，再把 ipa 取回来。

用法（在本机，git 与 ssh 已配好）：
    python tools/publish.py --repo qiaozhixiang/superlocator --private
    python tools/publish.py --dry-run                     # 只看会推哪些文件
    python tools/publish.py --wait --download out         # 推完盯构建、把 ipa 拉回来

认证优先级：
    1. --token / GITHUB_TOKEN（PAT，含 repo 权限）→ 能自动建仓库、查运行、下载 artifact
    2. 没有 token → 走 SSH 推（仓库必须已存在），运行状态只能用 --release-url 方式看
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]          # work/ios
STAGE = ROOT / ".publish" / "repo"
SKIP_PARTS = {"build", "out", "dist", "__pycache__", ".publish", ".git"}
DEFAULT_REPO = "qiaozhixiang/superlocator"
API = "https://api.github.com"


def run(cmd, cwd=None, check=True, capture=False):
    r = subprocess.run(cmd, cwd=str(cwd) if cwd else None, shell=isinstance(cmd, str),
                       capture_output=capture, text=True, encoding="utf-8", errors="replace")
    if check and r.returncode != 0:
        print((r.stdout or "") + (r.stderr or ""))
        raise SystemExit(f"命令失败：{cmd}")
    return r


def api(path: str, token: str | None, method="GET", body=None):
    req = urllib.request.Request(API + path, method=method)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, data=data, timeout=30) as r:
            raw = r.read().decode("utf-8")
            return r.status, (json.loads(raw) if raw.strip() else {})
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw)
        except json.JSONDecodeError:
            return e.code, {"message": raw[:300]}


def collect_files():
    files = []
    files.append((ROOT / "ci" / "ios-ipa.yml", Path(".github/workflows/ios-ipa.yml")))
    for p in sorted(ROOT.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(ROOT)
        if any(part in SKIP_PARTS for part in rel.parts):
            continue
        if p.suffix in (".pyc", ".log") or p.name in (".DS_Store",):
            continue
        files.append((p, Path("work/ios") / rel))
    return files


def stage_repo():
    files = collect_files()
    STAGE.mkdir(parents=True, exist_ok=True)
    if not (STAGE / ".git").exists():
        run(["git", "init", "-b", "main"], cwd=STAGE)
        run(["git", "config", "user.name", "SuperLocator Bot"], cwd=STAGE)
        run(["git", "config", "user.email", "qiaozhixiang@users.noreply.github.com"], cwd=STAGE)
    for src, rel in files:
        dst = STAGE / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    run(["git", "add", "-A"], cwd=STAGE)
    msg = "ios: 超级虚拟定位 iOS 版（工程 + 伴侣程序 + 网页版 + 测试 + 文档）"
    diff = run(["git", "status", "--porcelain"], cwd=STAGE, capture=True).stdout.strip()
    if diff:
        run(["git", "commit", "-m", msg], cwd=STAGE)
        print(f"已提交 {len(diff.splitlines())} 个文件变更")
    else:
        print("工作区无变更（复用上次提交）")
    return files


def ensure_repo(repo: str, token: str | None, private: bool) -> bool:
    if not token:
        print("没有 token：跳过创建，直接按已存在的仓库推送")
        return True
    status, data = api(f"/repos/{repo}", token)
    if status == 200:
        print(f"仓库已存在：{data.get('html_url')}")
        return True
    status, data = api("/user/repos", token, "POST", {
        "name": repo.split("/")[-1], "private": private,
        "description": "超级虚拟定位 · iOS 版（轨迹录制/重放 + 权重抖动 + 预设路径）",
        "auto_init": False,
    })
    if status in (200, 201):
        print(f"已创建仓库：{data.get('html_url')}")
        return True
    print(f"创建失败 HTTP {status}: {data.get('message')}")
    return False


def push(repo: str, remote_override: str | None):
    remote = remote_override or f"git@github.com:{repo}.git"
    r = run(["git", "remote", "get-url", "origin"], cwd=STAGE, check=False, capture=True)
    if r.returncode == 0 and r.stdout.strip() != remote:
        run(["git", "remote", "set-url", "origin", remote], cwd=STAGE)
    elif r.returncode != 0:
        run(["git", "remote", "add", "origin", remote], cwd=STAGE)
    print(f"推送到 {remote} …")
    out = run(["git", "push", "-u", "origin", "HEAD:main"], cwd=STAGE, check=False, capture=True)
    print((out.stdout or "").strip() or (out.stderr or "").strip())
    return out.returncode == 0


def wait_run(repo: str, token: str | None, timeout_s: int) -> dict | None:
    if not token:
        print("没有 token，无法查询运行状态；到仓库 Actions 页看即可")
        return None
    deadline = time.time() + timeout_s
    seen = None
    while time.time() < deadline:
        status, data = api(f"/repos/{repo}/actions/runs?per_page=5", token)
        if status == 200 and data.get("workflow_runs"):
            run0 = data["workflow_runs"][0]
            seen = run0
            print(f"  run #{run0['run_number']} status={run0['status']} conclusion={run0.get('conclusion')}")
            if run0["status"] == "completed":
                return run0
        time.sleep(20)
    return seen


def download_release(repo: str, token: str | None, outdir: Path) -> int:
    status, data = api(f"/repos/{repo}/releases/tags/ipa-latest", token)
    if status != 200:
        print(f"还没有 Release（HTTP {status}）：{data.get('message')}")
        return 0
    outdir.mkdir(parents=True, exist_ok=True)
    n = 0
    for asset in data.get("assets", []):
        url = asset["browser_download_url"]
        if any(url.endswith(ext) for ext in (".ipa", ".tipa")):
            dst = outdir / asset["name"]
            req = urllib.request.Request(url)
            if token:
                req.add_header("Authorization", "Bearer " + token)
            with urllib.request.urlopen(req, timeout=120) as r, dst.open("wb") as f:
                shutil.copyfileobj(r, f)
            print(f"  下载 {asset['name']}  {dst.stat().st_size} 字节")
            n += 1
    return n


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=DEFAULT_REPO)
    ap.add_argument("--token", default=os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN"))
    ap.add_argument("--private", action="store_true", help="建私有仓库（默认公开；公开才能免登录下载 Release）")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--remote", help="覆盖 git 远端（自测用，例如 file:///tmp/bare.git）")
    ap.add_argument("--wait", action="store_true", help="推送后盯着 Actions 运行")
    ap.add_argument("--timeout", type=int, default=1800)
    ap.add_argument("--download", help="构建完成后把 ipa/tipa 下到这个目录")
    args = ap.parse_args()

    files = stage_repo()
    print(f"待推送 {len(files)} 个文件 → {STAGE}")
    if args.dry_run:
        for src, rel in files[:12]:
            print("  " + str(rel))
        print(f"  …… 共 {len(files)} 个")
        return 0

    if args.token:
        st, me = api("/user", args.token)
        print(f"token 身份：{me.get('login')}（HTTP {st}）")
        if st != 200:
            print("token 无效或权限不足，改走 SSH")
            args.token = None

    ensure_repo(args.repo, args.token, args.private)
    if not push(args.repo, args.remote):
        print("推送失败：检查 SSH 公钥是否已加到 GitHub（ssh -T git@github.com）")
        return 2
    print(f"已推送：https://github.com/{args.repo}")
    if args.wait:
        run0 = wait_run(args.repo, args.token, args.timeout)
        if run0:
            print(f"结论 {run0.get('conclusion')}  {run0.get('html_url')}")
    if args.download:
        n = download_release(args.repo, args.token, Path(args.download))
        print(f"取回 {n} 个文件 → {args.download}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())