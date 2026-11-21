#!/usr/bin/env bash
# make_image.sh -- 在 Linux / WSL / macOS 上把一个「客户零电脑」的盒子镜像做出来
# 用法：
#   sudo bash make_image.sh --out SuperLocator-box.img --size 4G
# 产物：可直接用 Raspberry Pi Imager / balenaEtcher 烧到 TF 卡，开机即服务。
set -euo pipefail

OUT="SuperLocator-box.img"
SIZE="4G"
MNT="/mnt/stvbox"
SRC="$(cd "$(dirname "$0")" && pwd)"
BOOT_MNT="/mnt/stvboot"

while [ $# -gt 0 ]; do
  case "$1" in
    --out) OUT="$2"; shift 2;;
    --size) SIZE="$2"; shift 2;;
    -h|--help) sed -n '2,8p' "$0"; exit 0;;
    *) echo "未知参数：$1" >&2; exit 2;;
  esac
done

if [ "$(uname -s)" = "Darwin" ]; then
  echo "macOS 上请改用：hdiutil create -size $SIZE -fs MS-DOS $OUT" >&2
  echo "或者直接在 Linux/WSL 里跑本脚本。" >&2
  exit 3
fi

command -v losetup >/dev/null || { echo "缺少 losetup（apt install util-linux）" >&2; exit 3; }
command -v mkfs.vfat >/dev/null || command -v mkfs.fat >/dev/null || { echo "缺少 mkfs.vfat（apt install dosfstools）" >&2; exit 3; }

echo "[1/7] 创建空镜像 $OUT（$SIZE）"
rm -f "$OUT"
truncate -s "$SIZE" "$OUT"

echo "[2/7] 分区（1 个 FAT32 分区，MBR）"
parted -s "$OUT" mklabel msdos
parted -s "$OUT" mkpart primary fat32 1MiB 100%
parted -s "$OUT" set 1 lba on

echo "[3/7] 挂载 loop 设备"
LOOP="$(losetup --find --show --partscan "$OUT")"
sleep 1
PART="${LOOP}p1"
[ -b "$PART" ] || PART="${LOOP}1"

echo "[4/7] 格式化 FAT32"
mkfs.vfat -F 32 -n STVBOX "$PART" >/dev/null

echo "[5/7] 写入启动脚本与离线包"
mkdir -p "$MNT"
mount "$PART" "$MNT"
trap 'umount "$MNT" 2>/dev/null || true; losetup -d "$LOOP" 2>/dev/null || true' EXIT

mkdir -p "$MNT/stvbox"
cp -f "$SRC/install.sh" "$MNT/stvbox/install.sh"
cp -f "$SRC/run.sh"     "$MNT/stvbox/run.sh"
chmod +x "$MNT/stvbox/"*.sh
# 允许把 companion 与台账一起塞进去，做到「盒子出厂即带全套」
if [ -d "$SRC/../companion" ]; then
  cp -a "$SRC/../companion" "$MNT/stvbox/companion"
fi
if [ -f "$SRC/../license/ledger.json" ]; then
  mkdir -p "$MNT/stvbox/license"
  cp -f "$SRC/../license/ledger.json" "$MNT/stvbox/license/ledger.json"
fi

cat > "$MNT/stvbox/FIRSTBOOT.txt" <<'TXT'
第一次开机自动执行（见 /etc/systemd/system/stv-firstboot.service）：

  /boot/stvbox/install.sh

它会：装 python3 + usbmuxd → 建 venv → 装 pymobiledevice3/zeroconf/qrcode
      → 注册 superlocator.service（Restart=always）
      → 打印二维码地址（手机扫码就能用）

客户侧只需要：插 TF 卡 → 通电 → 手机连同一个 WiFi → 扫盒子上的二维码。
全程不碰电脑。
TXT

echo "[6/7] 生成 firstboot 说明完成，卸载"
sync
umount "$MNT"
trap - EXIT
losetup -d "$LOOP"

echo "[7/7] 完成：$OUT ($(du -h "$OUT" | cut -f1))"
cat <<EOT

烧录：
  Raspberry Pi Imager → Choose OS → Use custom → $OUT
  或  sudo dd if=$OUT of=/dev/sdX bs=4M status=progress conv=fsync

烧完后第一次开机要做的（把 boot 分区里的 firstboot 服务挂上）：
  若用自定义镜像（本脚本产物只含数据分区），在 config.txt 末尾追加
  init=/bin/bash -c "mount -o remount,rw /; /boot/stvbox/install.sh; exec /sbin/init"
  更稳的做法：直接用官方 Raspberry Pi OS Lite 镜像 + 在 boot 分区放一个
  firstrun.sh（见 docs 里的 firstrun 片段），本脚本产物的 /stvbox 目录直接拷进去即可。
EOT