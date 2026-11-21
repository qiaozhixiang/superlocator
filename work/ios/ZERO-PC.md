# 零电脑方案（ZERO-PC）

> 目标：客户拿到手的东西，**他自己一次都不用打开电脑**。
> 结论先说：iOS 的「写坐标」这件事必须有个宿主进程（DVT 服务只对宿主开放）。
> 所以「零电脑」只有两种实现方式：**把宿主做成盒子**，或者**让设备自己有权限（越狱/TrollStore + 端上 DDI）**。
> 卖家的电脑可以承担一次性的准备工作，客户侧保持零开关。

---

## 一、三条真正零电脑的路

### 路线 Z1：成品盒子（推荐，覆盖全版本）

客户侧动作只有三个：插 TF 卡 → 通电 → 手机连同一 WiFi 后扫码。

| 环节 | 谁做 | 说明 |
| --- | --- | --- |
| 烧卡 | 卖家（或代工厂） | `box/make_image.sh` 或 `box/firstrun.sh` 一条命令 |
| 首次开机装环境 | 盒子自己 | `firstrun.service` → `/opt/stvbox/install.sh` → systemd |
| 挂 DDI、起隧道 | 盒子自己 | `box/run.sh`：`mounter auto-mount` 重试 5 次 + `start-tunnel` |
| 手机配对 | 客户 | 插线，手机上点一次「信任」 |
| 日常使用 | 客户 | 手机浏览器打开 `http://superlocator.local:47655`（mDNS 自动发现，或用盒底二维码） |

要点：
- **手机侧那次「信任」躲不掉**，这是 iOS 强制的，任何方案都一样；点一次之后同一盒子不再问。
- 盒子断网也能用（局域网），只有 DDI 首次下载需要网。
- 一台盒子可服务多台手机（依次插线即可），适合店铺/工作室场景。

### 路线 Z2：TrollStore + 端上 DDI（设备 ≤17.0，无盒子）

客户侧动作：装一次 TrollStore（≤16.6.1 可用 kfd 纯端上；14.0–15.4.1 用 OTA 网页安装）→ 装我们的 tipa → App 内点「端上模式」。

此时不再需要电脑的条件是**两件都成立**：
1. 设备已有 TrollStore（一次性，卖家可代做）；
2. App 内自带 DDI 并在启动时自己挂上（`ondevice/DDIMounter.swift`，见下）。

### 路线 Z3：越狱插件（checkm8 全系 / 15.0–16.6.1）

装一次 `LocSim.deb` 后，**永久无线、无盒子、无电脑**。
代价：重启掉越狱（半绑定），客户要会重新跑一次 palera1n（那一步需要电脑）。

---

## 二、端上 DDI 是什么、为什么它能砍掉电脑

`com.apple.dt.simulatelocation` 这个 mach 服务不是系统自带的，它由**开发者磁盘镜像（DDI）**提供；
DDI 平时由 Xcode 或 `pymobiledevice3 mounter auto-mount` 从宿主挂载。
如果 App 自己能挂 DDI，就不需要宿主了 —— 这就是 Z2 的关键一步。

`ondevice/DDIMounter.swift` 的做法（与 TrollStore 生态里 `opainject`/`TrollFools` 同思路）：

1. `dlopen("/System/Library/PrivateFrameworks/MobileImageMounter.framework/MobileImageMounter")`；
2. `NSClassFromString("MobileImageMounter")` → `sharedInstance`；
3. 读包内 `ddi/<version>/BuildManifest.plist` 与 `Image.dmg`（+ `Image.dmg.trustcache`）；
4. `copyDevices()` 拿 PersonalizationIdentifiers（需要 `com.apple.private.mobile_image_mounter`）；
5. `mountImage:imagePath:imageType:options:completion:`，`imageType` 用 `"Personalized"`；
6. 挂载成功后立刻 `DTXLocation.shared.connect()`。

需要的 entitlements（已在 `ondevice/entitlements.plist` 里）：
`com.apple.private.mobile_image_mounter`、`com.apple.private.dvt.simulatelocation`、
`platform-application`、`com.apple.private.security.no-container`。

DDI 镜像来源（任选）：
- 卖家从一台 Mac 上 `~/Library/Developer/Xcode/iOS DeviceSupport/<版本>/` 取；
- 或 `pymobiledevice3 mounter` 下载缓存目录里取；
- 下载好后放进 `SuperLocator.app/ddi/17.0/`（约 100 MB，注意 App 体积与 TrollStore 安装上限）。

失败时 App 会明确报出这一步错在哪（`DDIMounter.lastError`），便于远程排查。

---

## 三、客户侧对比表（拿去做销售话术）

| | 零电脑 | 无线 | 重启后还要不要弄 | 覆盖版本 | 成本 |
| --- | --- | --- | --- | --- | --- |
| 盒子 Z1 | ✅ | ✅（同 WiFi） | 不用（盒子自启） | 全版本 | ¥150–200/台 |
| TrollStore Z2 | ✅（设备已装 TS） | ✅ | 可能要重挂 DDI | ≤17.0 | 0 |
| 越狱 Z3 | 首次要一次 | ✅ | 要重越（半绑定） | checkm8 / ≤16.6.1 | 0 |
| 电脑直连 | ❌ | ❌ | 要重插 | 全版本 | 0 |

---

## 四、卖家一次性准备清单（做成品交付）

1. 烧一张卡：`sudo bash box/make_image.sh --out SuperLocator-box.img --size 4G`
2. 或直接改官方镜像：把 `box/` 目录拷进 boot 分区，放 `firstrun.sh`，加 `firstrun.service`；
3. 盒子贴上二维码贴纸（`python -m pymobiledevice3` 无关，直接用 `/qr.png` 打印）；
4. 激活码按台发（`acttool keygen --device-hash <设备码>` 绑机），或发通用码后按台账记账；
5. 出厂自检三条：`curl /api/status` 返回 `ok`、`/qr.png` 是 200、`license/ledger.json` 存在。

---

## 五、边界（别对客户承诺过头）

- 盒子必须**通电 + 手机插线**（或同一 WiFi 下已配对）；拔线即回真实坐标。
- 17.1+ 无法越狱、无 TrollStore，只有盒子这一条。
- 端上 DDI（Z2）需要 DDI 镜像与 TrollStore 的 entitlements 生效，个别系统版本 `mountImage` 参数不同，需要真机跑一轮。
- 手机重启后 DDI 失效，盒子会自动重挂；Z2 需要重开 App 触发重挂。