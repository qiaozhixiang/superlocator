#!/usr/bin/env bash
# 盒子启动脚本：优先走 iOS 17 的 RSD 隧道，解析不到就按老系统（usbmux）跑。
set -uo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="$DIR/venv/bin/python"
[ -x "$PY" ] || PY="$(command -v python3)"
LOG=/var/log/superlocator.log

echo "[$(date '+%F %T')] run.sh start  py=$PY"

RSD_HOST=""
RSD_PORT=""
if "$PY" -m pymobiledevice3 remote start-tunnel --help >/dev/null 2>&1; then
    echo "[..] 尝试启动 RSD 隧道（iOS 17+ 必须）"
    "$PY" -m pymobiledevice3 remote start-tunnel >/tmp/rsd.log 2>&1 &
    TUN_PID=$!
    for _ in $(seq 1 40); do
        sleep 0.25
        RSD_HOST=$(grep -oE 'RSD address[: ]+[^ ,]+' /tmp/rsd.log | head -1 | awk '{print $NF}')
        RSD_PORT=$(grep -oE 'RSD port[: ]+[0-9]+' /tmp/rsd.log | head -1 | awk '{print $NF}')
        [ -n "$RSD_HOST" ] && [ -n "$RSD_PORT" ] && break
        kill -0 $TUN_PID 2>/dev/null || break
    done
    if [ -n "$RSD_HOST" ] && [ -n "$RSD_PORT" ]; then
        echo "[OK] RSD 隧道就绪 $RSD_HOST:$RSD_PORT"
    else
        echo "[..] 没拿到 RSD（可能不是 17+ 或没插线），按 usbmux 模式跑"
        kill $TUN_PID 2>/dev/null || true
        RSD_HOST=""; RSD_PORT=""
    fi
fi

# 先挂开发者磁盘镜像（DDI）：DVT 服务就在镜像里，重插线/重启后需要重挂
for i in 1 2 3 4 5; do
    if "$PY" -m pymobiledevice3 mounter auto-mount >/tmp/ddi.log 2>&1; then
        echo "[OK] DDI 已挂载"
        break
    fi
    echo "[..] 等设备就绪，重试挂载 DDI ($i/5)"
    sleep 3
done

ARGS=(serve --engine lib --license-dir "$DIR/license")
[ -n "$RSD_HOST" ] && ARGS+=(--rsd "$RSD_HOST:$RSD_PORT")

exec "$PY" "$DIR/superlocator.py" "${ARGS[@]}" 2>&1 | tee -a "$LOG"