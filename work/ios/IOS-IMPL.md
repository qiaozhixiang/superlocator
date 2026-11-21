# iOS 功能实现方案（三条真能跑通的路）

结论先说：iOS 上没有「装个 App 就能改全机定位」的公开 API。苹果把写系统定位的能力锁在
开发者服务 `com.apple.dt.simulatelocation`（DVT / DeveloperDiskImage）后面，而这条通道
**只能由持有该服务权限的进程调用**。所以「在 iPhone 上实现和 Android 一样的效果」只有三条
真正可行，区别只在「谁来调这个服务」。

---

## 路线 A：电脑伴侣程序（已交付，非越狱，系统级）

**谁在写坐标**：电脑上的 `superlocator.exe` 通过 USB（或同一局域网配对）调用 DVT 服务，写入的坐标
在系统层就是"真实定位"，地图、微信、打卡 App 全都读到它，**没有任何 App 能看出是假的**。

**你的包里已经有的东西**

| 文件 | 作用 |
| --- | --- |
| `dist/SuperLocator-windows.zip`（207MB 解压） | 电脑端：`superlocator.exe` + 三个 bat + 授权台账 |
| `out/SuperLocator-ios-kit.zip` / `SuperLocator-repo.zip` | iOS 端 SwiftUI App 源码 + CI 出 ipa |
| `http://<电脑IP>:47655/` | iPhone Safari 直接用的网页版（不用装 App） |

**最短可跑步骤（10 分钟）**

```powershell
# 1. 解压到非系统目录（不要在 Program Files / 下载目录里直接跑）
Expand-Archive .\SuperLocator-windows.zip -DestinationPath D:\SuperLocator
# 2. 解除"来自网络"的锁定（不解除会被 SmartScreen 拦）
Get-ChildItem D:\SuperLocator -Recurse | Unblock-File
# 3. 装苹果 USB 驱动（只需一次）
winget install --id Apple.AppleDevices -e
# 4. 双击 D:\SuperLocator\start-service.bat —— 窗口别关
```

手机端：

1. iPhone 插线，弹「信任此电脑」点信任；
2. Safari 打开 `http://<电脑IP>:47655/`，在「授权」栏输入激活码；
3. 手动模式填坐标，或轨迹 / 预设路径 → 开始，手机上的定位就跟着走。

**离线能不能用**：能。DVT 走的是本机 usbmux，不需要互联网；网页版的瓦片第一次需要联网，
之后浏览器会缓存。想让完全断网也能用，见路线 A+。

**路线 A+：把它做成"不用电脑"**（成本最低的常驻方案）
把 `D:\SuperLocator` 放到一台常开的机器上（旧笔记本 / 迷你主机 / 树莓派 4B 装 Windows ARM 或
Linux 跑 `superlocator.py`），手机与它同处一个 Wi-Fi。手机端甚至不用装 App，浏览器书签就行。

---

## 路线 B：TrollStore 端上 DVT（无电脑，需 TrollStore）

**谁在写坐标**：iPhone 自己的一个被 TrollStore 授予特权签名的 App，直接向
`com.apple.dt.simulatelocation` 服务投递坐标。因为进程有 `platform-application` 之类的伪签名，
系统把它当"开发者工具"放行。

**前提（三个都满足才行）**

1. 系统版本在 TrollStore 支持区间（14.0–17.0，具体以 TrollStore 发布页表格为准）；
2. 开了「开发者模式」（设置 → 隐私与安全性 → 开发者模式），并且至少要挂载过一次开发者镜像；
3. 有电（这条路比 A 耗电，因为要保持 mach 连接）。

**做法**：装一个 LocSim 类 App（TrollStore 商店里有同类工具，或自己用 Swift 写一个：
`import Darwin` 后 `bootstrap_look_up("com.apple.dt.simulatelocation")` 建 mach 连接，
按 DTX 协议发 `DTXMessage`）。它是系统级的，效果与路线 A 完全一致，但**不需要电脑**。

**能力边界**：坐标是"全局"的；但**不能**在本机运行我们的轨迹编辑器（那部分是 Swift App 的事，
两者可以共存：LocSim 负责写，我们的 App 负责算好后把坐标喂过去）。

---

## 路线 C：越狱插件（工程已给，`work/ios/jailbreak/`）

**谁在写坐标**：注入到每个 App（以及可选 SpringBoard）的 dylib，把
`CLLocationManager.location` / `CLLocation.coordinate` 的返回值换掉。10Hz 沿预设路径推进、
带抖动，**完全离线、不需要电脑、不需要开发者模式**。代价：必须越狱。

**环境**

| 越狱 | 支持系统 | 设备 |
| --- | --- | --- |
| palera1n | 15.0–17.x（部分） | A11 及更早（iPhone X 及以前） |
| Dopamine | 15.0–16.6.1 | A12–A16 |
| XinaA15 | 15.0–15.4.1 | A12–A15 |
| 其他 | 以发布页为准 | — |

rootless（`/var/jb`）与 rootful 都支持：Makefile 里用 `THEOS_PACKAGE_SCHEME=rootless` 切换。

**构建（在 macOS / Linux / WSL 上）**

```bash
git clone --recursive https://github.com/theos/theos.git ~/theos
export THEOS=~/theos
cd work/ios/jailbreak
make package THEOS_PACKAGE_SCHEME=rootless      # -> packages/com.stv.locsim_1.0.0_iphoneos-arm.deb
# rootful 去掉 THEOS_PACKAGE_SCHEME
```

装包：`scp packages/*.deb root@<手机IP>:/var/mobile/` 然后 `ssh root@<手机IP> "dpkg -i /var/mobile/*.deb"`
（或 Filza 里点开 deb 安装），装完 `killall -9 SpringBoard`。

**下发一条路径（用我们已有的工具）**

```bash
python work/ios/tools/make_locsim_plist.py work/ios/companion/samples/route_campus.json \
  -o work/ios/jailbreak/com.stv.locsim.plist --radius 15 --bias 0.6 --bearing 90 --loop
scp work/ios/jailbreak/com.stv.locsim.plist root@<手机IP>:/var/mobile/Library/Preferences/
ssh root@<手机IP> "killall -HUP backboardd"    # 或发 Darwin 通知 com.stv.locsim.reload
```

**配置字段**

| 键 | 类型 | 含义 |
| --- | --- | --- |
| `enabled` | BOOL | 总开关，false 时立刻恢复真实定位 |
| `lat` / `lng` | REAL | 单点模式坐标 |
| `radius` | REAL | 抖动半径（米），0 = 不抖 |
| `biasWeight` | REAL | 0..1，越大越集中在 `biasBearing` 方向 |
| `biasBearing` | REAL | 度；`nan` = 每次随机方向 |
| `route` | ARRAY | `[{lat,lng,speed}]`，有则沿路径走 |
| `loop` | BOOL | 到终点后回到起点 |

**恢复真实定位**：`enabled=false` + 重载，或直接卸载 deb + 重启。

---

## 三条路对比

| | A 电脑伴侣 | B TrollStore 端上 DVT | C 越狱插件 |
| --- | --- | --- | --- |
| 需要越狱 | 否 | 否 | 是 |
| 需要电脑常开 | 是 | 否 | 否 |
| 需要开发者模式 | 否 | 是 | 否 |
| 系统级（其他 App 也生效） | 是 | 是 | 是 |
| 完全离线 | 是（局域网） | 是 | 是 |
| 永久不过期 | 取决于签名方式 | 是（TrollStore） | 是 |
| 已交付状态 | 已交付 + 已测 21/12/17 项 | 需装第三方 App | 工程已给，需自行 `make package` |

## 怎么选（照着走）

1. **不想折腾系统**、有电脑可用 → 路线 A（今天就能用，包里全套都在）。
2. **iPhone 系统在 TrollStore 区间**、想要"只有手机" → 路线 B。
3. **已经越狱**、想要零依赖 + 完全离线 → 路线 C（我给的 `work/ios/jailbreak/` 直接编）。

---

## 我们这边还能继续做的

- 把路线 C 的 tweak 加一个「悬浮球」UI（SpringBoard 里常驻，点一下切换开关/切路径）；
- 给路线 C 写 CI（Theos 在 Linux runner 上能编 deb），产物直接下载；
- 给路线 B 写一个最小 Swift 实现（`com.apple.dt.simulatelocation` 的 DTX 客户端），这样不依赖第三方 App。