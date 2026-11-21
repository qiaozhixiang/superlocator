#!/bin/bash
# firstrun.sh -- 放到 Raspberry Pi OS Lite 的 boot 分区，首次开机自动装好一切
# 客户侧：烧卡 → 通电 → 手机扫码。零电脑。
set -e

LOG=/boot/firstrun.log
exec > >(tee -a "$LOG") 2>&1
echo "== stvbox firstrun $(date -Is) =="

# WiFi（可选：把 wpa_supplicant.conf 一并放进 boot 分区即可跳过这段）
if [ -f /boot/wpa_supplicant.conf ]; then
  cp -f /boot/wpa_supplicant.conf /etc/wpa_supplicant/wpa_supplicant.conf
fi

# 主机名固定，方便客户在路由器里认出来（可选）
hostnamectl set-hostname superlocator-box || true

apt-get update -y
apt-get install -y python3 python3-venv python3-pip usbmuxd curl

mkdir -p /opt/stvbox
cp -a /boot/stvbox/. /opt/stvbox/ 2>/dev/null || true
chmod +x /opt/stvbox/*.sh

bash /opt/stvbox/install.sh || echo "[firstrun] install.sh 返回非 0，见日志"

# 自删，避免第二次开机重复执行
systemctl disable firstrun.service 2>/dev/null || true
rm -f /etc/systemd/system/firstrun.service
echo "== stvbox firstrun done =="