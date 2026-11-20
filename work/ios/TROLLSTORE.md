# 路线 D：TrollStore 永久安装（不用 Apple ID、不过期）

TrollStore 利用 CoreTrust 的签名校验缺陷（CVE-2023-41991）做「永久签名」：装进去的 App
不受证书约束、不会 7 天过期、不用连电脑续签、桌面图标和普通 App 一样。

它替我们干了「签名」这件事，所以这条路 **完全不需要 Apple ID**，只要两样东西：

1. 你自己手机上装好 **TrollStore**（前提是系统版本在它支持的区间内）；
2. 一个 **编译好的未签名包** `SuperLocator.tipa`（由 CI 或 Mac 产出，见第 3 节）。

---

## 1. 先确认你的系统在不在支持区间

设置 → 通用 → 关于本机 → 软件版本，记下完整版本号（形如 `16.6.1`、`17.0`）。

| 系统版本 | TrollStore 支持情况 | 装机方式 |
| --- | --- | --- |
| iOS 14.0 – 15.4.1 | 支持 | TrollHelperOTA（Safari 直接装） |
| iOS 15.5 – 15.6.1 | 支持 | TrollHelperOTA |
| iOS 16.0 – 16.6.1 | 支持 | TrollInstallerX / Misaka |
| iOS 16.7 – 17.0 | 部分设备支持（与机型、芯片相关） | TrollRestore（要电脑） |
| iOS 17.0 以上（17.1+） | 一般不在支持区间 | 走路 A（Mac）或路 B（Sideloadly） |

TrollStore 的支持区间会随版本更新变化，最终以它的发布页标注为准（GitHub `opa334/TrollStore` 的
README 有一张按系统版本 + 芯片型号列的表）。版本号落在表内才继续往下走。

---

## 2. 装 TrollStore 本体的三种方式

### 2.1 iOS 14.0 – 15.6.1：TrollHelperOTA（最快，全程在手机上）

1. Safari 打开 TrollStore 官方页面，点 `Install TrollStore`（会跳到 `itms-services://` 的 OTA 描述）；
2. 弹窗「要在“设置”中打开吗」→ 允许 → 设置里装好一个叫 **TrollStore Helper** 的 App；
3. 打开 Helper → 点 `Install TrollStore` → 回到桌面，TrollStore 就装好了。

### 2.2 iOS 16.0 – 16.6.1：TrollInstallerX

TrollInstallerX 本身是个普通 App，需要签一次才能跑（用免费 Apple ID + Sideloadly 签，7 天足够，
因为装完 TrollStore 之后就永久了）：

1. 下载 `TrollInstallerX.ipa`；
2. Sideloadly 选这个 ipa、填 Apple ID 与 App 专用密码 → `Start`；
3. 手机上信任证书（设置 → 通用 → VPN 与设备管理）；
4. 打开 TrollInstallerX → `Install TrollStore` → 选一个用来做持久化的系统 App（`提示`/Tips）→ 完成。

### 2.3 iOS 16.7 – 17.0：TrollRestore（要电脑，正好复用我们的 pymobiledevice3 环境）

TrollRestore 走「备份恢复」路径把 TrollStore 塞进系统 App 里，命令如下（电脑装好
`pymobiledevice3`，手机连上并信任）：

```bash
# 1) 拿到 TrollRestore（发布页给的压缩包，解压后是一个 python 脚本）
python trollrestore.py            # 按提示选设备、输入要做持久化的系统 App 名（如 Tips）
# 2) 手机会重启一次；重启后打开「提示」App，里面就是 TrollStore 的安装入口
```

跑完把 `提示`（Tips）保留着别删 —— 它是 TrollStore 的持久化载体，系统更新前也不要动它。

---

## 3. 产出 `SuperLocator.tipa`

### 3.1 走 GitHub Actions（不需要 Mac）

把 [work/ios/ci/ios-ipa.yml](work/ios/ci/ios-ipa.yml) 放到仓库 `.github/workflows/` 下，
`Actions → ios-ipa → Run workflow`，跑完在 Artifacts 里会同时拿到：

- `SuperLocator-unsigned.ipa`
- `SuperLocator.tipa`（内容与 ipa 字节相同，只是后缀让「文件」App 交给 TrollStore 处理）

### 3.2 有 Mac 时本地出包

```bash
cd work/ios
METHOD=none bash build_ipa.sh          # 无签名构建 + 打 ipa
python3 tools/make_ipa.py --app build/dd/Build/Products/Release-iphoneos/SuperLocator.app \
        --out build/SuperLocator-unsigned.ipa --tipa
```

### 3.3 手上已有 ipa，只想要 tipa

两者字节完全一致，改名即可（TrollStore 也接受 `.ipa`，`.tipa` 只是让分享菜单默认出现它）：

```bash
python work/ios/tools/make_ipa.py --check SuperLocator-unsigned.ipa   # 先体检
cp SuperLocator-unsigned.ipa SuperLocator.tipa
```

体检通过的标准（`--check` 会逐条打印）：`cf bundle executable` 指向的二进制在位、
`_CodeSignature/CodeResources` 在位、`embedded.mobileprovision` 在位。TrollStore 只要求第一条与
「Mach-O 架构匹配」；后两条它自己会补上（ldid fakesign + 伪描述文件）。

---

## 4. 把 tipa 装进手机

### 方式一：文件 App 里点开（最省事）

1. 用 AirDrop / 微信文件传输 / 局域网传到 iPhone；
2. 「文件」App 里点 `SuperLocator.tipa` → 分享菜单 → `TrollStore` → `Install`；
3. 桌面出现「超级虚拟定位」图标，点开即可。

### 方式二：TrollStore 内 `+`

TrollStore 右上角 `+` → 选 `SuperLocator.tipa` → `Install`。

### 方式三：URL 直装（适合批量/远程）

```bash
# 电脑上把 tipa 所在目录用局域网 HTTP 暴露
cd work/ios/build && python -m http.server 8000
# 手机 Safari 打开（把 IP 换成电脑的 IPv4）
apple-magnifier://install?url=http://192.168.1.20:8000/SuperLocator.tipa
```

---

## 5. 装完必须做的一步：Persistence Helper

TrollStore → `Settings` → `Install Persistence Helper` → 选一个你基本不用的系统 App（`提示` / `音乐`）。

这一步的作用：iOS 重启后，TrollStore 靠这个被替换的系统 App 重新拿到执行入口；不做的话，
某些版本重启后 TrollStore 打不开，已装的 App 还在但没法再装新包。

装完可以顺手在 TrollStore → `Settings` 里确认：

- `URL Scheme` 已启用（方式三要用）；
- `Enable LiteSigning`（TrollStore 2 的选项，装了 ldid 之后自动可用）保持默认；
- 我们这版 App **不需要任何自定义 entitlement**，所以 `Entitlements` 里不用改任何东西。

---

## 6. TrollStore 装完之后，链路怎么跑

TrollStore 只解决「把 App 装进手机」。写坐标仍然走电脑伴侣程序（iOS 没有本地改定位的接口）：

```bash
# 电脑
python -m pymobiledevice3 mounter auto-mount
python work/ios/companion/superlocator.py serve --engine lib --port 47654
```

手机：打开「超级虚拟定位」→ 允许定位、允许本地网络 → 顶部天线图标填电脑 IPv4 → 连接 →
用 `samples/track_campus.json` 试一次重放。

TrollStore 版和证书版的差别只有一点：**永不过期、不用重新签名、也没有 3 个自签 App 的上限**。
与伴侣程序的协议、轨迹库位置、MapKit 选点、抖动公式全都不变。

---

## 7. 排障

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| `文件` App 里点开 tipa 没有 TrollStore 选项 | 未开启 URL Scheme / 分享菜单没加载 | TrollStore → Settings → 打开 URL Scheme，或在 TrollStore 里用 `+` 装 |
| TrollStore 报 `Unable to install` | 包结构不对（缺可执行文件 / 架构不匹配） | 先 `python tools/make_ipa.py --check x.tipa`，确认二进制与架构 |
| 装上了但点开闪退 | 二进制是 arm64e 而设备是 arm64（或反之） | 重新出包时加 `ARCHS="arm64 arm64e"`，或只保留 `arm64`（iOS 真机默认就是 arm64） |
| 重启后 TrollStore 打不开 | 没装 Persistence Helper | 重装 TrollStore，装完立刻设 Helper |
| 桌面没图标 | SpringBoard 缓存 | TrollStore 里长按该 App → `Refresh Icon Cache`，或重启一次 |
| 装不上、提示系统版本不支持 | 你的系统在区间之外 | 走路 A（Mac + Xcode）或路 B（Sideloadly 重签） |
| 想删掉 | — | TrollStore 里左滑 `Uninstall`；Persistence Helper 会同时还原成原系统 App |

---

## 8. 这条路的边界

- TrollStore 的可用性取决于系统版本，系统一旦升级到区间之外就装不上了（已装的 App 会随系统更新一起清掉）；
- 它改的是签名校验这一层，不改系统分区，卸载 TrollStore 后已装 App 一并消失；
- 我们的 App 仍然要电脑在旁写坐标 —— 这一点跟路线 A / B 完全一样，TrollStore 不改变数据通路。