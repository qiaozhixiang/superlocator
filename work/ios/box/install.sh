#!/usr/bin/env bash
# 超级虚拟定位 · 定位盒子一键安装（树莓派 / 任意 Debian 12+ 小主机）
#
# 用法（在盒子上跑一次，2~3 分钟）：
#   sudo bash install.sh
#
# 装完之后：
#   手机插到盒子 USB 口 → 手机上点「信任」→ 手机 Safari 打开 http://superlocator.local:47655/
set -euo pipefail

APP_DIR=/opt/superlocator
SVC=/etc/systemd/system/superlocator.service
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"   # work/ios

say() { printf '\033[36m==> %s\033[0m\n' "$*"; }
die() { printf '\033[31m[x] %s\033[0m\n' "$*" >&2; exit 1; }

[ "$(id -u)" = "0" ] || die "要用 root 跑：sudo bash install.sh"

say "1/6 装系统依赖（usbmuxd 是让盒子能读 iPhone 的驱动）"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3 python3-pip python3-venv usbmuxd libusbmuxd-tools \
    avahi-daemon ca-certificates curl >/dev/null

say "2/6 建目录 + 拷程序"
mkdir -p "$APP_DIR"
install -m 0644 "$SRC_DIR/companion/superlocator.py"   "$APP_DIR/"
install -m 0644 "$SRC_DIR/companion/webapp_page.py"   "$APP_DIR/"
install -m 0644 "$SRC_DIR/companion/licensing.py"     "$APP_DIR/"
install -m 0755 "$SRC_DIR/box/run.sh"                 "$APP_DIR/run.sh"

say "3/6 装 python 依赖（首次会下 ~40MB）"
python3 -m venv "$APP_DIR/venv" 2>/dev/null || true
"$APP_DIR/venv/bin/pip" install -q --upgrade pip
"$APP_DIR/venv/bin/pip" install -q pymobiledevice3 zeroconf qrcode

say "4/6 首次配对（手机会弹「信任此电脑」，点信任并输密码）"
if pymobiledevice3 --version >/dev/null 2>&1; then
  :
else
  ln -sf "$APP_DIR/venv/bin/pymobiledevice3" /usr/local/bin/pymobiledevice3
fi
"$APP_DIR/venv/bin/python" -m pymobiledevice3 usbmux list || true

say "5/6 写 systemd 服务（开机自启 + 崩溃重拉）"
cat > "$SVC" <<UNIT
[Unit]
Description=SuperLocator box service (iPhone location over usbmuxd)
After=network-online.target usbmuxd.service
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=$APP_DIR
Environment=PYTHONUNBUFFERED=1
Environment=TZ=Asia/Shanghai
ExecStart=$APP_DIR/run.sh
Restart=always
RestartSec=3
StandardOutput=append:/var/log/superlocator.log
StandardError=append:/var/log/superlocator.log

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable superlocator >/dev/null
systemctl restart superlocator
sleep 4

say "6/6 自检"
IP=$(hostname -I | awk '{print $1}')
if curl -fsS "http://127.0.0.1:47655/api/status" >/dev/null 2>&1; then
  echo "  [OK] 服务已起来"
else
  echo "  [!!] 服务没起来，看日志：journalctl -u superlocator -n 50 --no-pager"
fi
if curl -fsS "http://127.0.0.1:47655/qr.png" >/dev/null 2>&1; then
  echo "  [OK] 二维码可用"
fi
if [ -f "$APP_DIR/license/ledger.json" ]; then
  echo "  [OK] 授权台账：$APP_DIR/license/ledger.json"
else
  echo "  [..] 还没台账，跑一次：cd $APP_DIR && ./venv/bin/python superlocator.py license init"
fi

cat <<DONE

============================================================
  装好了。后面只需要三步：
  1) 手机用数据线插到盒子，解锁，点「信任」
  2) 手机 Safari 打开：  http://superlocator.local:47655/
     （不行就用 IP：    http://$IP:47655/）
  3) 页面顶部粘激活码 → 激活 → 选轨迹 / 路径 → 开始

  常用命令：
    systemctl status superlocator      # 看状态
    journalctl -u superlocator -f      # 看日志
    systemctl restart superlocator     # 重启
============================================================
DONE