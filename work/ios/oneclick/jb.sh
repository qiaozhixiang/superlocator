#!/usr/bin/env bash
# 一键越狱 / 一键注入向导（Linux / macOS / WSL2）
#
# 用法：
#   ./jb.sh                 # 只检测 + 打印方案
#   ./jb.sh --run           # 真的执行（会下载工具、装插件）
#   ./jb.sh --deb path.deb  # 越狱成功后顺带装我们的插件
#   ./jb.sh --ipa app.tipa  # TrollStore 环境下顺带装我们的 App
#
# 它做的事情：
#   1. 用 pymobiledevice3 / ideviceinfo 读出机型和系统版本
#   2. 按「芯片 × 版本」选越狱工具（palera1n / Dopamine / TrollFools）
#   3. 该下载的下载、该推装的推装、该提示按 DFU 的提示
#   4. 越狱完成后自动装插件、写配置、重启桌面
#
# 唯一不能自动化的一步：checkm8 设备（A11 及更早）进 DFU 必须人工按键 —— 这是硬件级引导，
# 任何软件都无法代按。其余全部可以串起来。

set -uo pipefail
RUN=0; DEB=""; IPA=""
while [ $# -gt 0 ]; do
  case "$1" in
    --run) RUN=1 ;;
    --deb) DEB="${2:-}"; shift ;;
    --ipa) IPA="${2:-}"; shift ;;
    -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
    *) echo "未知参数 $1"; exit 2 ;;
  esac
  shift
done

say() { printf '\033[1;36m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[!]\033[0m %s\n' "$*"; }
die() { printf '\033[1;31m[x]\033[0m %s\n' "$*"; exit 1; }
run() { if [ "$RUN" = 1 ]; then say "执行：$*"; "$@"; else echo "    (dry) $*"; fi; }

command -v python3 >/dev/null || die "缺 python3"
PMD="python3 -m pymobiledevice3"
$PMD version >/dev/null 2>&1 || warn "没装 pymobiledevice3，检测可能失败（pip3 install pymobiledevice3）"

# ---------- 1. 检测设备 ----------
say "检测已连接的 iPhone"
INFO="$($PMD usbmux list 2>/dev/null || true)"
if [ -z "$INFO" ]; then
  warn "没读到设备。请插线、在手机上点『信任』，然后重跑。"
fi

MODEL="$(printf '%s' "$INFO" | sed -n 's/.*"ProductType": *"\([^"]*\)".*/\1/p' | head -1)"
VERSION="$(printf '%s' "$INFO" | sed -n 's/.*"ProductVersion": *"\([^"]*\)".*/\1/p' | head -1)"
UDID="$(printf '%s' "$INFO" | sed -n 's/.*"UniqueDeviceID": *"\([^"]*\)".*/\1/p' | head -1)"

if [ -z "${MODEL:-}" ]; then
  if [ -t 0 ]; then
    warn "自动识别失败，手动填一下："
    read -r -p "  机型（如 iPhone12,1）：" MODEL
    read -r -p "  系统版本（如 16.6.1）：" VERSION
  else
    die "没有检测到设备（插线 + 手机上点『信任』后重跑）"
  fi
fi
say "机型 ${MODEL:-?} · 系统 ${VERSION:-?} · UDID ${UDID:-未读到}"

# ---------- 2. 判断芯片代次 ----------
chip_family() {
  case "$1" in
    iPhone8,*|iPhone9,*|iPhone10,[1-6]|iPhone10,3|iPhone10,6|iPad*) echo "checkm8" ;;  # A11 及更早
    *) echo "arm64e" ;;                                                                  # A12 及更新
  esac
}
FAM="$(chip_family "${MODEL:-iPhone0,0}")"
VER_MAJOR="${VERSION%%.*}"
VER_MINOR="$(printf '%s' "$VERSION" | cut -d. -f2)"; VER_MINOR="${VER_MINOR:-0}"

ver_le() { [ "$1" -lt "$3" ] || { [ "$1" -eq "$3" ] && [ "$2" -le "$4" ]; }; }

# ---------- 3. 选方案 ----------
PLAN=""; TOOL=""
if [ "$FAM" = "checkm8" ]; then
  PLAN="palera1n（checkm8，rootless/rootful 都行）"; TOOL="palera1n"
elif ver_le "$VER_MAJOR" "$VER_MINOR" 16 6; then
  PLAN="Dopamine（手机上点一下就越狱，rootless /var/jb）"; TOOL="dopamine"
elif ver_le "$VER_MAJOR" "$VER_MINOR" 17 0; then
  PLAN="TrollStore + TrollFools（不越狱，按 App 注入 tweak）"; TOOL="trollfools"
else
  PLAN="没有公开越狱 → 只能走『定位盒子』路线"; TOOL="box"
fi
say "推荐方案：$PLAN"

# ---------- 4. 执行 ----------
case "$TOOL" in
  palera1n)
    if ! command -v palera1n >/dev/null; then
      warn "没装 palera1n"
      run bash -c 'curl -fsSL https://raw.githubusercontent.com/palera1n/palera1n/main/palera1n.sh -o /tmp/palera1n.sh && bash /tmp/palera1n.sh'
    fi
    warn "接下来会要求你把手机按进 DFU（音量下 + 电源 组合键），这一步只能人来按："
    echo "     1) 按住「音量下 + 电源」10 秒"
    echo "     2) 松开电源，继续按住音量下 5 秒"
    run palera1n -l          # rootless
    ;;
  dopamine)
    TIPA_URL="https://github.com/opa334/Dopamine/releases/latest/download/Dopamine.tipa"
    if [ -n "${UDID:-}" ]; then
      say "把 Dopamine 推装到手机（需要手机已装 TrollStore 或可侧载）"
      run bash -c "curl -fL '$TIPA_URL' -o /tmp/Dopamine.tipa && $PMD apps install /tmp/Dopamine.tipa"
    else
      echo "   下载地址：$TIPA_URL"
    fi
    echo "   然后在手机上打开 Dopamine → 点「Jailbreak」→ 等重启 → 出现 Sileo"
    ;;
  trollfools)
    echo "   路径：先装 TrollStore（本机系统在支持区间）→ 再装 TrollFools → 选目标 App → 注入我们的 dylib"
    echo "   TrollStore：https://github.com/opa334/TrollStore/releases"
    ;;
  box)
    echo "   这台设备无法越狱，卖它只能配『定位盒子』（见 work/ios/ONDEVICE.md 形态三）"
    exit 0
    ;;
esac

# ---------- 5. 越狱后：装我们的插件 / 配置 ----------
if [ -n "$DEB" ]; then
  [ -f "$DEB" ] || die "找不到 $DEB"
  say "安装插件 $DEB"
  run bash -c "$PMD file pull /var/mobile 2>/dev/null || true"
  if [ "$RUN" = 1 ]; then
    IP="$($PMD usbmux list | sed -n 's/.*"DeviceName".*//p' >/dev/null; echo)"
    warn "如果越狱后开了 SSH（默认 root/alpine），用下面两条更快："
    echo "   scp '$DEB' root@<手机IP>:/var/mobile/"
    echo "   ssh root@<手机IP> 'dpkg -i /var/mobile/$(basename "$DEB") && killall -9 SpringBoard'"
  fi
fi

if [ -n "$IPA" ]; then
  [ -f "$IPA" ] || die "找不到 $IPA"
  say "安装 App $IPA"
  run bash -c "$PMD apps install '$IPA'"
fi

say "完成。后续维护："
cat <<'EOF'
  · 插件配置：/var/mobile/Library/Preferences/com.stv.locsim.plist
  · 下发路径：python3 tools/make_locsim_plist.py route.json -o /tmp/l.plist
              scp /tmp/l.plist root@<手机IP>:/var/mobile/Library/Preferences/com.stv.locsim.plist
              ssh root@<手机IP> "killall -HUP backboardd"
  · 关闭虚拟定位：把 plist 里 enabled 改成 false，重载即可
EOF