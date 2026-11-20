# 超级虚拟定位 · iOS 版

把 Android 版「超级虚拟定位」的四项核心功能原样搬到 iPhone 上：

1. **录制轨迹** —— 把注入出去的坐标流按位移/时间采样存成轨迹；
2. **重放轨迹** —— 沿时间轴自动移动，100 ms 一帧；
3. **随机值 / 权重偏于** —— 半径 + 权重 + 方位角，注入点围着轨迹基准点抖；
4. **预设路径** —— 地图点选节点连成路径，每段独立速度或跟随全局，速度偏移量决定每段速度区间；
   轨迹与路径都存本地并分组。

---

## 1. 为什么 iOS 需要一个「电脑端伴侣程序」

Android 版能改写系统定位，是因为它自己调 `LocationManager.addTestProvider` / `setTestProviderLocation`
（配合开发者选项选为「模拟位置信息应用」）。iOS 没有等价 API：

- App 沙盒里拿不到任何能写系统定位的接口；
- 唯一能让全系统（含微信、钉钉、地图、打卡 App）都读到假坐标的通道，是**开发者服务**里的
  `com.apple.dt.simulatelocation`（Xcode 的「模拟位置」用的就是它）。

这条通道必须由**外部主机**通过 USB 调用。所以本项目拆成两半：

```
┌──────────────────────────────┐         ┌───────────────────────────────┐        ┌──────────────┐
│  iPhone · SuperLocator.app   │  TCP    │  电脑 · superlocator.py       │  USB   │  iPhone 系统  │
│  · 轨迹库 / 分组 / 录制       │ 47654   │  · serve：接收坐标帧           │ DVT    │  · 全系统定位 │
│  · 重放引擎（插值 + 抖动）    │ ──────▶ │  · play：自己按时间轴播放      │ ─────▶ │    被改写     │
│  · 预设路径（每段速度）       │ JSON    │  · pymobiledevice3 写入        │        │              │
│  · 地图选点（MapKit）        │ 行协议   │                               │        │              │
└──────────────────────────────┘         └───────────────────────────────┘        └──────────────┘
```

App 负责「算」，伴侣程序负责「写」。好处是：轨迹库、分组、路径编辑、可视化预览全在手机上离线可用；
只有「真的把位置写进系统」这一步需要电脑。

> 如果你的 iPhone 越狱了，也可以把伴侣程序换成越狱插件（hook `CLLocationManager`），但这不在本仓库范围里；
> 不越狱、不装描述文件、不改系统分区，是这套方案的默认前提。

---

## 2. 目录

```
ios/
├── README.md                       本文
├── lint_swift.py                   括号/结构自检（没有 Xcode 时也能跑）
├── SuperLocator/
│   ├── project.yml                 XcodeGen 工程描述（bundle id: com.stv.locator）
│   └── Sources/
│       ├── App/SuperLocatorApp.swift
│       ├── Model/Models.swift       轨迹 / 分组 / 路径（JSON 与 Android、伴侣程序一致）
│       ├── Core/GeoMath.swift       haversine / bearing / offset / Catmull-Rom
│       ├── Core/Jitter.swift        「权重偏于」公式（与 Android 逐行对齐）
│       ├── Core/Stores.swift        本地库：VTracks/{groups,index}.json + 分组目录
│       ├── Core/Engines.swift       注入会话 / 录制器 / 重放引擎 / 路径引擎
│       ├── Net/CompanionClient.swift TCP 行分隔 JSON 客户端
│       ├── Views/RootView.swift     四页签 + 连接页 + 通用组件
│       ├── Views/RecordView.swift   录制页 + 轨迹库页 + GPX/JSON 导出
│       ├── Views/ReplayView.swift   重放页 + Canvas 轨迹预览
│       ├── Views/RouteView.swift    预设路径页（节点速度、全局速度、偏移量）
│       ├── Views/MapPickView.swift  MapKit 选点（搜索 / 缩放 / 撤销 / 恢复）
│       └── Resources/Assets.xcassets（AppIcon 1024、AccentColor）
└── companion/
    ├── superlocator.py             伴侣程序（Windows / macOS 都能跑）
    ├── protocol.md                 TCP 协议
    ├── requirements.txt
    ├── samples/track_campus.json   示例轨迹
    ├── samples/route_campus.json   示例预设路径
    └── tests/test_all.py           10 条自检（几何、抖动、速度区间、协议）
```

---

## 3. 编译 iOS App

需要一台 **macOS + Xcode 15**（iOS 17 SDK）。没有 Mac 的话，App 的代码可以直接丢进任意
Xcode 工程编译；伴侣程序在 Windows 上就能跑，部分功能（导出轨迹 → 电脑播放）也就不依赖 Mac。

```bash
# 1) 装 XcodeGen（只用来生成工程文件）
brew install xcodegen

# 2) 生成工程
cd ios/SuperLocator
xcodegen generate

# 3) 打开、选真机、跑
open SuperLocator.xcodeproj
```

签名：Xcode → Target → Signing & Capabilities → 选自己的 Team。
免费 Apple ID 也能装，只是证书 **7 天**过期，过期后 App 打不开，重新跑一次 Xcode 即可（数据不丢，存在 App 沙盒里）。
模拟器没有「模拟位置」通道，必须真机。

首次启动要做三件事：

1. **信任电脑**（插线时手机上点「信任」）；
2. **开发者模式**：设置 → 隐私与安全性 → 开发者模式 → 打开 → 重启；
3. 允许「本地网络」与「定位」权限（定位只用于取起始参考点，不用于注入）。

---

## 4. 电脑端准备（Windows / macOS）

```bash
python -m pip install pymobiledevice3
```

USB 插上 iPhone（Windows 需装 iTunes 或 Apple Devices 的驱动），然后：

```bash
# 看设备有没有认出来
python -m pymobiledevice3 usbmux list

# iOS 17+ 必须先挂载开发者镜像（DDI）
python -m pymobiledevice3 mounter auto-mount

# 起服务，等 App 连
python superlocator.py serve --engine lib --port 47654
```

在 App 顶部点天线图标 → 填电脑的**局域网 IP**（`ipconfig` 里的 IPv4）→ 连接。

### iOS 17 及以上：隧道模式

iOS 17 起 DVT 端口不再走 usbmux 明文，需要 RSD 隧道：

```bash
# 另开一个窗口，保持运行
sudo python -m pymobiledevice3 remote start-tunnel --script-mode
# 输出里会有 RSD Address / RSD Port，形如 127.0.0.1 49152

# 用隧道地址起服务
python superlocator.py serve --engine lib --rsd 127.0.0.1:49152
```

`superlocator.py play` / `set` / `clear` 同样支持 `--rsd`。用 `--engine cli` 可以完全走命令行通道
（速率建议 ≤ 2 Hz，适合慢速步行；10 Hz 请用 `--engine lib`）。

---

## 5. 功能对照（Android ↔ iOS）

| 功能 | Android（原交付包） | iOS（本项目） |
| --- | --- | --- |
| 注入通道 | `LocationManager.addTestProvider` + `setTestProviderLocation`（100 ms） | 电脑 `pymobiledevice3` → DVT `simulate-location`（10 Hz） |
| 录制 | `Recorder`：500 ms / 位移 ≥1 m / 5 s 兜底 | `Recorder`：同样的三条规则，`Sources/Core/Engines.swift` |
| 分组存储 | `files/vtracks/groups.json + index.json + <groupId>/<trackId>.json` | `Documents/VTracks/…`，目录与文件格式完全一致 |
| 重放 | `ReplayEngine`：Catmull-Rom + 100 ms tick + speed 0.1~20 | `ReplayEngine`：同一套插值与限速 |
| 随机抖动 | `Jitter`：半径 / 权重 / 方位角，4~9 s 重采样，一阶低通 1.2 s，限幅 1.5R | `Jitter`：逐行同公式，含 Rayleigh(σ=0.55) 与 180°×(1−w)+12° 扩散 |
| 预设路径 | `RouteEngine`：每段基准速度 ×(1±偏移)，2.5 s 重采样，0.2~25 m/s 限幅 | `RouteEngine`：同公式，`Sources/Core/Engines.swift` |
| 地图选点 | 自写 `vmap.html` + 高德栅格瓦片 | MapKit（苹果地图）+ `MKLocalSearch` 搜索 + 缩放/撤销/恢复 |
| 轨迹预览 | `TrackPreviewView`（Canvas 折线 + 基准点/注入点） | `TrackPreviewView`（SwiftUI Canvas，同样画法） |
| 分组筛选 / 移动 / 重命名 | 轨迹库页 | 轨迹库页（长按菜单） |
| GPX 导出 | 写 `getExternalFilesDir("tracks")` | 系统分享面板（存到「文件」、发微信、AirDrop） |
| 悬浮摇杆 | 原 App 的 `JoyStick`（保留） | 无（iOS 不允许跨 App 悬浮窗），手动改坐标改为 App/伴侣程序 `set` |
| 通知小图标 | `ic_stat_track` | 系统「正在使用定位」由 iOS 自己控制 |

---

## 6. 数据格式（三端通用）

轨迹（`track_*.json`）：

```json
{
  "id": "t_sample_001",
  "name": "校园跑道一圈",
  "groupId": "default",
  "createdAt": 1730000000000,
  "intervalMs": 1000,
  "points": [[0, 36.710210, 117.021550], [1000, 36.710310, 117.021640]]
}
```

`points` 每项是 `[相对毫秒, 纬度, 经度]`，与 Android 版的 `TrackPoint.toJson` 一致。

预设路径（`route_*.json`）：

```json
{
  "id": "r_sample_001",
  "name": "图书馆到操场",
  "globalSpeed": 1.4,
  "offsetPercent": 25,
  "loop": false,
  "nodes": [[36.710210, 117.021550, 0.0], [36.710380, 117.021900, 2.2]]
}
```

`nodes` 每项是 `[纬度, 经度, 该段基准速度]`，第三项 `0` 表示「跟随全局」。

这样三端可以直接互拷：

- Android 录的轨迹 → 传到 iPhone 的 `Documents/VTracks/<group>/` → App 里直接重放；
- iPhone 导出的 JSON → `python superlocator.py play --file x.json` 在电脑上播；
- GPX 可以喂给任何轨迹工具。

---

## 7. 精度与算法细节

**为什么用 100 ms 一帧**：Android 版原服务是 100 ms 灌一次，iOS 侧保持一致，两个平台的时间轴才能对齐；
DVT 通道 10 Hz 完全吃得下（实测单帧写入 < 5 ms）。

**Catmull-Rom**：轨迹点稀疏（1 m 一个）时线性插值会出现折角，重放出来的速度曲线是阶梯。
Catmull-Rom 用前后各一个点做切线，位置连续、速度也连续，App 与伴侣程序用的是同一个公式（`GeoMath.interpolate` / `Player._position_at`）。

**抖动公式**（两端一致）：

```
baseMag   = radius · w · (0.5 + 0.5u)                 u ~ U(0,1)
spread    = 180° · (1 − w) + 12°                      w ≥ 0.999 时取 3°
wobbleMag = radius · (1 − 0.65w) · Rayleigh(σ=0.55)
target    = 极坐标(baseBearing, baseMag) + 极坐标(baseBearing + N(0, spread), wobbleMag)
重采样    : 每 4~9 秒一次
输出      : 一阶低通 k = 1 − exp(−dt/1.2)，限幅 radius × 1.5
```

`w=0` 时目标点退化为随机游走；`w=1` 时几乎只朝 `baseBearing` 方向偏，扩散只剩 ±3°。
`radius=0` 表示关闭抖动，注入点严格落在轨迹上。

**预设路径速度区间**：`实际速度 = 段基准速度 × (1 ± 偏移%/100)`，每 2.5 秒重采一次，
再限幅到 `[0.2, 25] m/s`。所以「偏移量 20%」意味着每段速度在基准的 0.8~1.2 倍之间变化，
不是每帧乱跳 —— 这一点与 Android 版 `RouteEngine.onTick` 完全一致。

---

## 8. 排障

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| `usbmux list` 空 | 没信任电脑 / 驱动缺失 | 手机上点「信任」，Windows 装 iTunes 或 Apple Devices |
| 报 `DeveloperMode is not enabled` | 开发者模式没开 | 设置 → 隐私与安全性 → 开发者模式 → 打开并重启 |
| 报 `ImageMountFailed` / `DDI` | 开发者镜像没挂 | `python -m pymobiledevice3 mounter auto-mount` |
| 报 `ConnectionRefused`（iOS 17+） | 没走隧道 | `pymobiledevice3 remote start-tunnel`，用 `--rsd host:port` |
| App 连不上电脑 | 不同网段 / 防火墙 | 手机与电脑同一 Wi-Fi；Windows 防火墙放行 47654 |
| 位置不动 | 伴侣程序没在跑，或 App 没点开始 | App 顶部看连接状态；`serve` 窗口应有 `客户端接入` 日志 |
| 位置跳回真实点 | 系统把注入清掉了 | 重新点「开始」；伴侣程序 `stop` 会主动 `clear`，别在播放中停 |
| 轨迹录出来只有 2 个点 | 位移阈值太大 | 录制页把「最小位移」调小到 0.5 m |
| 走完最后一帧位置不动 | 播放已到终点（非循环） | 打开「循环」，或重新开始 |

---

## 9. 自检

```bash
cd ios/companion
python tests/test_all.py        # 10 条：几何、抖动上界、强偏向方向、速度区间、TCP 协议
python superlocator.py play --file samples/route_campus.json --engine dry --loop
```

`--engine dry` 不需要 iPhone，只打印坐标，用来验证轨迹/路径与算法是否符合预期。

Swift 侧没有 Xcode 时可以先跑结构自检：

```bash
python ios/lint_swift.py        # 括号平衡 + 行数（在 SuperLocator/Sources 目录下执行）
```

---

## 10. 边界说明

- 本项目不修改 iOS 系统分区、不装描述文件、不越狱；用的是苹果官方开发者通道。
- 免费开发者账号签名 7 天过期；付费账号 1 年。过期只需重装，数据在沙盒里不受影响。
- 电脑必须保持连接（USB 或同一局域网），因为「写坐标」这一步在电脑上。App 可以离线做规划、编辑、
  预览、导出，联网后一键播放。
- 注入的坐标在系统层就是「真实定位」，其他 App 读到的是普通 `CLLocation`，**没有** Android 那种
  `isFromMockProvider=true` 标记。这是 iOS 通道与 Android 通道的天然差异。

## 11. 网页版：iPhone 上不用装任何东西就能用

`serve` 除了给原生 App 开 TCP 47654，还会在 **47655** 上开一个网页版（`--http-port` 可改，0 = 关）。手机 Safari 打开电脑的局域网地址即可，无需签名、无需 ipa、无需开发者模式：

```bash
dist\superlocator.exe serve --engine lib --port 47654
# 屏幕会打印：网页版 http://192.168.x.x:47655/
```

手机端页面自带三页：

| 页 | 内容 |
| --- | --- |
| 手动 | 直接设经纬度、用手机定位填坐标、抖动半径/权重/方位角 |
| 轨迹 | 用手机真实定位录一段 → 分组保存（Safari localStorage）→ 预览 → 重放（速度/循环/抖动） |
| 预设路径 | 高德瓦片地图点选节点（WGS-84↔GCJ-02 自动换算）、每段速度或全局速度、速度偏移、沿路径播放 |

页面 → 伴侣程序走 `POST /api/cmd`（与 TCP 同一套命令：`set`/`jitter`/`play`/`pause`/`resume`/`stop`/`status`），`GET /` 发页面，`GET /api/status` 查状态。自检：`python tools/test_web.py`（源码）、`python tools/test_web.py --exe`（编译产物）——12 项全过，含「页面 200 / 地图容器 / play 后确实有帧」。

**网页版与原生 App 的差别**：没有原生 App 的跨 App 悬浮窗、没有后台常驻；Safari 进后台时页面轮询会被节流，播放仍由电脑端驱动（坐标照常写），只是页面上的进度刷新会变慢。真机装机仍走 ipa（第 3/4 章）。
