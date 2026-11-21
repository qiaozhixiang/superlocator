# 无电脑方案（可售卖形态）

## 一句硬结论

**没越狱、没装 TrollStore 的普通 iPhone，任何软件都无法自己写系统定位。**
这不是技术不够，是苹果的内核限制：写定位必须走 `com.apple.dt.simulatelocation` 这个私有
mach 服务，而只有「被授予该 entitlement 的进程」才连得上。普通 App 拿不到这个 entitlement，
签名也不会通过。所以"完全不要任何外部设备、卖给任意 iPhone 用户"在技术上不存在。

能卖的只有三种形态，覆盖面和门槛各不相同。

---

## S1 · TrollStore 版（手机自己搞定，最接近"App"的体验）

| 项 | 内容 |
| --- | --- |
| 用户操作 | Safari 打开下载页 → 下载 `.tipa` → 用 TrollStore 打开 → 装好，桌面出现图标 |
| 需要条件 | 系统在 TrollStore 支持区间（14.0–17.0，按版本选 TrollStore/TrollHelperOTA/TrollInstallerX/TrollRestore） |
| 是否要电脑 | 装的时候不要，之后也不要 |
| 生效范围 | 全系统（地图、微信、打卡 App 都读到假坐标） |
| 我们的实现 | App 内 `DTXLocation.swift` 直连 mach 服务，坐标由 App 自己的轨迹/路径引擎算 |
| 授权 | 离线 HMAC 激活码（设备绑定），与我们 Android 版同一套算法 |

技术上需要三样东西，都在 `work/ios/ondevice/`：

1. `DTXLocation.swift` —— 连 `com.apple.dt.simulatelocation`，发 `setLocation:`；
2. `entitlements.plist` —— `com.apple.private.dvt.simulatelocation` + `platform-application` 等；
3. 打包：`ldid -Sentitlements.plist` 伪签名 → 压成 `Payload/XXX.app` → 改后缀 `.tipa`。

**这条路必须在真机上过一遍**：私有框架名字、selector 名（`setLocation:` / `simulateLocation:`）
在不同系统版本上有差异，我这边没有 iPhone，只能在你有设备时按 `DTXLocation.swift` 末尾的
调试顺序逐条验证。

---

## S2 · 越狱版（deb，能力最强，完全离线）

| 项 | 内容 |
| --- | --- |
| 用户操作 | Sileo/Zebra 里加我们的源 → 一键安装 → 重启桌面 |
| 需要条件 | 已越狱（palera1n / Dopamine / XinaA15 等，按机型版本） |
| 是否要电脑 | 越狱那一步可能要；装完之后完全不要 |
| 我们的实现 | `work/ios/jailbreak/` 的 tweak（已写好，hook CoreLocation） |
| 授权 | 插件内置校验，读我们的授权文件 |

这条的代码已经完整：`Tweak.xm` + `Makefile` + `control`，`make package` 出 deb。

---

## S3 · 盒子版（覆盖全部机型，最好卖）

| 项 | 内容 |
| --- | --- |
| 用户操作 | 盒子插电、iPhone 插一次线配对 → 之后手机浏览器打开 `http://盒子IP:47655` |
| 需要条件 | 任何 iPhone（不需要越狱、不需要 TrollStore） |
| 是否要电脑 | 不要——盒子不是电脑，是个插电的小盒子，出厂预装好 |
| 硬件 | 树莓派 Zero 2 W（或任意 ARM 小主机）+ 5V 电源 + 外壳 + TF 卡，BOM ≈ ¥160 |
| 软件 | 就是我们的 `superlocator` + `usbmuxd`，开机自启，自带授权台账 |
| 授权 | 盒子与激活码绑定，一盒一码；可加"到期时间"字段 |

为什么它绕开了苹果的限制：写坐标的进程在盒子里，盒子通过 USB/Wi-Fi 与 iPhone 的 usbmux 通信，
iPhone 本身不需要任何特权。用户视角就是"买个盒子，手机就能改定位"。

出厂镜像可以做成：刷好系统的 TF 卡（插上即用），或整机销售。

---

## 覆盖面（决定你卖谁）

| 机型/系统 | S1 TrollStore | S2 越狱 | S3 盒子 |
| --- | --- | --- | --- |
| iOS 14–17.0（可装 TrollStore） | ✅ 首选 | ✅ | ✅ |
| iOS 15–16.6.1（可越狱 A12–A16） | 视 TrollStore 支持 | ✅ 首选 | ✅ |
| iOS 17.1+ 未越狱 | ❌ | ❌ | ✅ 唯一可行 |
| iPad 同上 | 同上 | 同上 | ✅ |

结论：**想卖所有人 → 只卖 S3；想卖玩家 → S1/S2 更轻。**

---

## 售卖时的防盗

1. 激活码与设备绑定（`deviceHash = sha256(设备标识 + 型号)`，一码一机）；
2. secret 不放在明文资源里：编进二进制常量、或放进 `.so`；
3. 一码一激活，本地台账记录已用 serial，重复用直接拒；
4. 需要"限时/限台数"时，加一个可选在线校验（10 行 Flask 就够），我们已有 `license` 服务端逻辑；
5. 盒子版可直接把授权写进盒子固件，用户拿不到 secret。

---

## 我现在能继续做的（按你选的形态）

- S1：把 `DTXLocation.swift` 接进现有 SwiftUI App，加 `project.yml` 的 TrollStore 构建配置、`ldid` 注入脚本、`.tipa` 打包脚本；
- S2：把 tweak 打成 deb + 建一个 Sileo 源（静态 `Packages` 文件即可）；
- S3：写盒子镜像制作脚本（Raspberry Pi OS Lite + usbmuxd + 开机自启 + 首次配对向导），出一张可烧录的 `.img` 说明。