# 编译 · 测试 · 出货（一条龙）

本工程有两个可执行体，编译环境完全不同：

| 目标 | 在哪编 | 能不能在本机（Windows）编 | 产物 |
| --- | --- | --- | --- |
| 电脑端伴侣程序 | Windows / macOS / Linux 都行 | **能，已编好并实测** | `superlocator.exe`（PyInstaller 单文件，7.0 MB） |
| iPhone App | 必须有 macOS + Xcode 15+（SwiftUI/MapKit 只随 iOS SDK 提供） | 不能 | `SuperLocator.ipa` / `.tipa` |

iPhone App 的编译放在 GitHub 的 macOS runner 上跑 —— 那条流水线同时把**单元测试**跑完才出包，等于「编译 + 测试」两步一条命令。

---

## 一、伴侣程序（本机已编好，可复现）

```bash
cd work/ios/companion
python -m pip install pyinstaller
python -m PyInstaller --onefile --name superlocator \
  --distpath ../build/exe --workpath ../build/pyi --specpath ../build/pyi -y superlocator.py
```

> Windows 注意：PyInstaller 单文件版启动时要解压到 `%TEMP%`。若宿主/杀软把临时目录锁了，会出现
> `Could not create temporary directory!`，把 `TEMP`/`TMP`/`TMPDIR` 指向一个有写权限的目录即可：
> `set TEMP=%CD%\build\tmp && set TMP=%TEMP% && set TMPDIR=%TEMP%`

编译完立刻自测（21 项，跑的是 **exe 本身**，不是源码）：

```bash
python work/ios/tools/test_exe.py --exe work/ios/build/exe/superlocator.exe
```

覆盖：子命令齐全、`serve` 起服务、TCP 握手、`ping/set/jitter/play/stop` 往返、播放时坐标真的在动、
抖动上界 ≤ 1.5R、`bias=0.9 / bearing=90°` 时 39/40 帧偏东、`play --engine dry` 命令行坐标流。

---

## 二、iPhone App（在 macOS runner 上编译 + 测试）

把 `work/ios/ci/ios-ipa.yml` 复制到仓库的 `.github/workflows/`，push 或手动 Run workflow。流水线顺序：

1. `brew install xcodegen` → `xcodegen generate`（工程由 `project.yml` 生成，含 `SuperLocatorTests` 测试 target）
2. **`xcodebuild test`（模拟器，先跑测试；失败就不继续出包）**
3. `xcodebuild build`（无签名）或 `archive`（配了证书 secrets）
4. `make_ipa.py` 打 ipa + 体检 + 复制 `.tipa`
5. 上传 artifact，同时打印 `shasum -a 256`

本机（有 Mac 时）等价命令：

```bash
cd work/ios/SuperLocator
xcodegen generate
xcodebuild test -project SuperLocator.xcodeproj -scheme SuperLocator \
  -destination 'platform=iOS Simulator,name=iPhone 15'
xcodebuild -project SuperLocator.xcodeproj -scheme SuperLocator -configuration Release \
  -destination 'generic/platform=iOS' -derivedDataPath ../build/dd \
  CODE_SIGNING_ALLOWED=NO build
python3 ../tools/make_ipa.py \
  --app ../build/dd/Build/Products/Release-iphoneos/SuperLocator.app \
  --out ../build/SuperLocator-unsigned.ipa --tipa
python3 ../tools/make_ipa.py --check ../build/SuperLocator-unsigned.ipa
```

### 测试都测了什么

`SuperLocator/Tests/CoreTests.swift`（16 个用例，模拟器内跑，不需要真机、不需要伴侣程序）：

| 组 | 用例 | 断言 |
| --- | --- | --- |
| 黄金向量 | `testGoldenDistance/Bearing/Offset/PointAlong/Interpolate` | 与 `tools/make_golden.py` 生成的 48 条向量逐条比对，距离 1e-6、经纬度 1e-9 |
| 抖动 | `testJitterZeroRadiusStaysZero` / `testJitterStaysWithinBound` / `testJitterBiasDirection` | 半径 0 恒为 0；3000 拍峰值 ≤ 1.5R；90° 偏向时平均偏东 |
| 轨迹 | `testTrackJsonRoundTrip` / `testNormalizeTimelineIsMonotonic` / `testTrackDistancePositive` / `testGpxHasAllPoints` | JSON 往返、时间戳严格递增、GPX 点数 |
| 预设路径 | `testRouteSegmentSpeeds` | 节点速度覆盖全局、段数/总长/预览 |
| 存储 | `testTrackStoreCRUD` / `testRouteStoreCRUD` | 建组→存→改名→移动→删除全链路落盘 |
| 契约 | `testCompanionPayloadShape` | `points` 必须是 `[t,lat,lng]` 三元组（与 Android 一致） |

黄金向量的意义：Android（Java `GeoMath`/`ReplayEngine.interpolate`）、伴侣程序（Python `Geo`/`_position_at`）与
iOS（Swift `GeoMath`）三套实现共用同一批数字，任何一处改坏都会被 XCTest 抓到。

### 功能齐备度（静态核对，本机可跑）

```bash
python work/ios/tools/verify_app.py
```

17 项功能逐条给出 `文件:行` 锚点（录制、分组、轨迹库增删改移、重放倍率/循环、权重偏于、预设路径、
每段速度、速度偏移量、地图点选/搜索/缩放/撤销恢复/回定位、Canvas 预览、TCP 伴侣连接、GPX 导出、
状态栏、定位权限、JSON 契约）。当前结果：**17/17**。

---

## 三、出货与清理：只留编译产物

```bash
# 1) 把产物收进 dist/（同时生成 SHA256SUMS.txt 与 MANIFEST.json）
python work/ios/tools/package_dist.py \
  --exe build/exe/superlocator.exe \
  --ipa build/SuperLocator-unsigned.ipa \
  --tipa build/SuperLocator.tipa \
  --zip out/SuperLocator-ios-kit.zip

# 2) 看一眼会删什么（不删）
python work/ios/tools/package_dist.py --ipa build/SuperLocator-unsigned.ipa --prune

# 3) 真删中间物（build/、out/、__pycache__、*.log），源码保留
python work/ios/tools/package_dist.py --ipa build/SuperLocator-unsigned.ipa --prune --yes

# 4) 连源码一起删，只留 dist/（彻底版）
python work/ios/tools/package_dist.py --ipa build/SuperLocator-unsigned.ipa --prune --prune-sources --yes
```

`dist/` 在清理后长这样：

```
dist/
  superlocator.exe              电脑端伴侣程序（已编译，直接双击/命令行运行）
  SuperLocator-unsigned.ipa     手机端 App（用 Sideloadly / AltStore / TrollStore 装）
  SuperLocator.tipa             TrollStore 直装格式
  SuperLocator-ios-kit.zip      源码 + 工具 + 测试（想改就解压这一份）
  SHA256SUMS.txt                产物指纹
  MANIFEST.json                 产物清单（大小/时间）
```

## 网页版自检

```bash
python tools/test_web.py          # 源码版：12 项（JS 语法 + HTTP 接口）
python tools/test_web.py --exe    # 编译产物版（先编 exe）
```

`--http-port` 默认 `--port + 1`（47655），`0` 关闭网页版。改完 `companion/webapp_page.py` 或 `companion/superlocator.py` 都要重编 exe 才会进 dist。
