# 不插手机、不越狱，能不能行？

一句话：**能，但只有一条路——设备上跑 TrollStore 版（Z2），装完之后永久无线、不越狱、不插线。**
除此之外的组合在 iOS 上物理不存在，原因写在最后一节。

---

## 一、四个条件的两两组合

| 不插线 | 不越狱 | 可行？ | 走哪条 | 说明 |
| --- | --- | --- | --- | --- |
| ✅ | ✅ | **可以** | **TrollStore 端上 DVT（Z2）** | 装好之后 App 自己挂 DDI、自己写坐标 |
| ✅ | ❌ | 可以 | 越狱插件（Z3） | 无线、无盒子，但重启要重越 |
| ❌ | ✅ | 可以 | 电脑 / 盒子（Z1） | 线是 DVT 隧道的物理通道 |
| ❌ | ❌ | 可以 | 越狱 + 电脑任选 | 没必要 |

注意：TrollStore **不是越狱**。它是 CoreTrust 签名绕过，不改内核、不装 SSH、不掉保修标记，重启也还在（只要装了 Persistence Helper）。

---

## 二、Z2 的真实前提（三条，缺一不可）

1. **系统 ≤ 17.0**（TrollStore 支持的版本上限）
   - 14.0–15.4.1：Safari 打开 OTA 页面就能装，纯手机；
   - 15.5–16.6.1：TrollInstallerX（kfd），纯手机，需开开发者模式；
   - 16.7–17.0：TrollRestore（备份恢复法，要一次电脑）或 checkm8 机型先越狱再装。
2. **App 内自带 DDI**（`ondevice/ddi/<版本>/`，`tools/inject_ddi.py` 塞进 tipa）；
3. **entitlements 生效**（`com.apple.private.dvt.simulatelocation` + `com.apple.private.mobile_image_mounter` + `platform-application`，`make_tipa.py` 负责）。

装完这之后：不插线 ✅、不越狱 ✅、重启后只要重开 App 就自动重挂 DDI ✅。

---

## 三、线到底在干什么（为什么普通 App 必须插）

DVT 的两个服务（`com.apple.dt.simulatelocation`、`com.apple.dt.dtxproxy`）不在系统本体里：

- 由**开发者磁盘镜像（DDI）**提供 → 线上靠宿主 `mounter auto-mount` 挂载；
- 调用它的进程必须持有 **Apple 私有 entitlement** → 正常签名的 App 拿不到；
- 隧道（`start-tunnel`）在 iOS 17 上必须由 USB 建立 → 所以拔线立即失效、位置回真实。

TrollStore 一次把后两道闸都打开了（伪签名给 entitlement、App 自己挂 DDI），于是线就没用了。

---

## 四、装完之后的使用形态

| 场景 | 操作 |
| --- | --- |
| 日常改位置 | 打开 App（或锁屏小组件/快捷指令唤起）→ 选轨迹/预设路径 → 开始 |
| App 被系统挂起 | `DTXKeepAlive` 每 5 秒重推一次，并申请 `beginBackgroundTask` 续命 |
| 手机重启 | DDI 掉，打开 App 自动重挂（`DDIMounter.mount()`），不用电脑 |
| 换轨迹 | 用我们的「轨迹重放 / 预设路径」界面，或把 plist 推进 App 容器 |

---

## 五、做不到的组合（别被销售话术骗）

- **不装任何东西、不插线、不越狱** → 无解。没有任何公开或私有 API 允许一个未授权的沙盒 App 改写 `locationd` 的输出。
- **蓝牙 / 隔空投送 / 描述文件** → 都不碰定位层。
- **企业证书签的普通 App** → 有签名没 entitlement，调用 DVT 直接被拒。
- **17.1 以上** → 既无 TrollStore 也无越狱，只剩插线（盒子/电脑）。

---

## 六、给客户的三种交付话术

1. 「装一次，之后永远不用插电脑」→ Z2（≤17.0）；
2. 「插上这个小盒子，手机扫码就用」→ Z1（全版本，含 17.1+）；
3. 「越狱一次，之后无线免维护（重启除外）」→ Z3。

三条都写在 `ZERO-PC.md` 里，配套脚本 `box/`（盒子镜像）、`ondevice/`（端上 DVT + DDI）、`jailbreak/`（deb）都已就位。