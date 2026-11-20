#!/usr/bin/env bash
# 在 macOS 上把 SuperLocator 源码编译成可安装的 .ipa
#
#   TEAM_ID=ABCDE12345 bash build_ipa.sh                 # 开发签名（连数据线直接装）
#   TEAM_ID=ABCDE12345 METHOD=ad-hoc bash build_ipa.sh   # 描述文件里带 UDID 的设备可装
#   METHOD=none bash build_ipa.sh                        # 不签名，产出给 Sideloadly / AltStore 重签
#
# 产物：build/export/SuperLocator.ipa（或 build/SuperLocator-unsigned.ipa）
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
METHOD="${METHOD:-development}"
SCHEME="${SCHEME:-SuperLocator}"
BUNDLE_ID="${BUNDLE_ID:-com.stv.locator}"
OUT="$ROOT/build/export"

if ! command -v xcodebuild >/dev/null 2>&1; then
  echo "[x] 这里没有 xcodebuild：本脚本要在 macOS + Xcode 15 上执行" >&2
  exit 2
fi
if ! command -v xcodegen >/dev/null 2>&1; then
  echo "[i] 安装 XcodeGen"
  brew install xcodegen
fi

cd "$ROOT/SuperLocator"
xcodegen generate --spec project.yml
mkdir -p "$ROOT/build"

if [ "$METHOD" = "none" ]; then
  echo "[i] 无签名构建（产物交给 Sideloadly / AltStore 重签）"
  xcodebuild -project SuperLocator.xcodeproj -scheme "$SCHEME" -configuration Release \
    -destination 'generic/platform=iOS' \
    -derivedDataPath "$ROOT/build/dd" \
    CODE_SIGNING_ALLOWED=NO CODE_SIGNING_REQUIRED=NO CODE_SIGN_IDENTITY="" \
    build
  APP="$ROOT/build/dd/Build/Products/Release-iphoneos/SuperLocator.app"
  python3 "$ROOT/tools/make_ipa.py" --app "$APP" --out "$ROOT/build/SuperLocator-unsigned.ipa"
  exit 0
fi

: "${TEAM_ID:?先 export TEAM_ID=你的10位TeamID（Xcode → Settings → Accounts 里能看到）}"

echo "[i] 归档（$METHOD，Team $TEAM_ID）"
xcodebuild -project SuperLocator.xcodeproj -scheme "$SCHEME" -configuration Release \
  -destination 'generic/platform=iOS' \
  -archivePath "$ROOT/build/SuperLocator.xcarchive" \
  -allowProvisioningUpdates \
  DEVELOPMENT_TEAM="$TEAM_ID" \
  PRODUCT_BUNDLE_IDENTIFIER="$BUNDLE_ID" \
  CODE_SIGN_STYLE=Automatic \
  archive

cat > "$ROOT/build/ExportOptions.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>method</key><string>${METHOD}</string>
  <key>teamID</key><string>${TEAM_ID}</string>
  <key>signingStyle</key><string>automatic</string>
  <key>signingCertificate</key><string>${CERT_NAME:-Apple Development}</string>
  <key>destination</key><string>export</string>
  <key>stripSwiftSymbols</key><true/>
  <key>thinning</key><string>&lt;none&gt;</string>
</dict>
</plist>
EOF

echo "[i] 导出 ipa"
rm -rf "$OUT"
xcodebuild -exportArchive \
  -archivePath "$ROOT/build/SuperLocator.xcarchive" \
  -exportPath "$OUT" \
  -exportOptionsPlist "$ROOT/build/ExportOptions.plist" \
  -allowProvisioningUpdates

IPA="$(ls "$OUT"/*.ipa | head -1)"
python3 "$ROOT/tools/make_ipa.py" --check "$IPA"
echo "[+] 完成：$IPA"