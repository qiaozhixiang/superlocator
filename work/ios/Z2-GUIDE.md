# Z2 全流程：不插线、不越狱的 TrollStore 版

> 适用：iPhone 系统 ≤ 17.0。
> 结果：装一次，之后永久无线、不越狱、不用电脑。
> 分工：**卖家**负责编包（需要一次 macOS 或 GitHub Actions）；**客户**负责装 App（手机点几下 + 传文件）。

---

## 0. 准备清单（按角色分）

### 卖家电脑（Windows 即可）

| 软件 | 版本 | 用途 | 装法 |
| --- | --- | --- | --- |
| Python | 3.10+（现有 3.12.10 可用） | 跑 `tools/*.py` | 已有 |
| 7-Zip | 任意 | 查看/拆 ipa、核对包内容 | `winget install 7zip.7zip` |
| Apple Devices 或 iTunes | 最新 | usbmuxd 驱动（签名/配对要用） | `winget install --id Apple.AppleDevices -e` |
| Sideloadly | 最新 | 给 TrollInstallerX 签一次名 | sideloadly.io 下载 |
| Git（可选） | 任意 | 推仓库给 CI | 已有 |

卖家**不需要**装：Xcode、Swift、ldid、pymobiledevice3、TrollStore。
（`make_tipa.py` 的伪签名在 CI 的 Linux/macOS 上做；Windows 不做签名。）

### 编译环境（二选一）

- **A. GitHub Actions（推荐，零 Mac）**：一个公开仓库 + 免费账号。CI 里已有 14 步：xcodegen → 单测 → 无签名构建 → 打 ipa → **打 tipa（塞 entitlements）** → **拉 DDI 并注入** → 校验 → artifact / Release。
- **B. 一台 Mac**：Xcode 16 + `brew install xcodegen`。命令见第三节。

### 客户手机

| 东西 | 说明 |
| --- | --- |
| TrollStore | 按系统版本装（见第 4 节），**不是越狱** |
| 开发者模式 | 设置 → 隐私与安全性 → 开发者模式 → 开 → 重启 |
| 我们的 tipa | 卖家给的最终包（内含 DDI + entitlements） |

---

## 1. 卖家：编出带 DDI 的 tipa

### 路线 A：GitHub Actions

```bash
# 1) 建一个空仓库（网页 create，Public），然后：
cd work/ios
python tools/publish.py --repo <你的账号>/superlocator --wait --download dist
```

`publish.py` 会：推 51 个文件 → 等 CI → 从 `releases/tag/ipa-latest` 拉回
`SuperLocator-unsigned.ipa`、`SuperLocator.trollstore.tipa` 到 `dist/`。

CI 中途会跑这两步（已在 workflow 里）：

```bash
python3 tools/fetch_ddi.py --ios 17.0 --variant personalized     # 下 DDI（17.1 MB）
python3 tools/inject_ddi.py --ipa SuperLocator.trollstore.tipa \
        --ddi ondevice/ddi/17.0 --ver 17.0 --out SuperLocator.trollstore.ddi.tipa
```

### 路线 B：本地 Mac

```bash
cd work/ios/SuperLocator
xcodegen generate
xcodebuild -scheme SuperLocator -configuration Release -sdk iphoneos \
           CODE_SIGNING_ALLOWED=NO -derivedDataPath ../build/dd build
cd ..
python tools/make_ipa.py --app build/dd/Build/Products/Release-iphoneos/SuperLocator.app \
        --out dist/SuperLocator-unsigned.ipa
python tools/make_tipa.py --ipa dist/SuperLocator-unsigned.ipa \
        --out dist/SuperLocator.trollstore.tipa --entitlements ondevice/entitlements.plist
python tools/fetch_ddi.py --ios 17.0
python tools/inject_ddi.py --ipa dist/SuperLocator.trollstore.tipa \
        --ddi ondevice/ddi/17.0 --ver 17.0 --out dist/SuperLocator.z2.tipa
```

### 卖家自检（三条，全过才算合格）

```bash
# ① 包内必须有 ddi/ 与二进制
unzip -l dist/SuperLocator.z2.tipa | grep -E "ddi/|SuperLocator.app/$"

# ② entitlements 必须进得去（Linux/mac 用 ldid -e 反查）
ldid -e dist/SuperLocator.z2.tipa 2>/dev/null | head   # 或解包后对二进制反查

# ③ 结构体检
python tools/make_ipa.py --check dist/SuperLocator.z2.tipa
```

预期：能看到 `Payload/SuperLocator.app/ddi/17.0/Image.dmg`，且 `--check` 里
「可执行文件 / Info.plist / 显示名」三项正常（未签名那两条属于预期）。

---

## 2. 客户：把 tipa 传进手机（不用线）

任选一条：

1. **AirDrop / 微信文件传输助手 / QQ 我的设备** → 存到「文件」App；
2. 卖家局域网起个服务：`python -m http.server 8000`，手机 Safari 下载；
3. iCloud Drive 共享链接。

传到手机后，文件在「文件 → 我的 iPhone → 下载」里。

---

## 3. 客户：装 TrollStore（一次，按版本选）

| 系统版本 | 方法 | 要不要电脑 |
| --- | --- | --- |
| 14.0–15.4.1 | Safari 打开 TrollStore 官方发布页 → 点安装（OTA） | 不要 |
| 15.5–16.6.1 | 用 Sideloadly 签一次 `TrollInstallerX.ipa` → 装上 → 打开点 Install TrollStore | 要（**仅这一步**） |
| 16.7–17.0（A12+） | TrollRestore（备份恢复法） | 要 |
| 16.7–17.0（checkm8，iPhone 8/X） | 先 palera1n 越狱再装，或直接走越狱插件 | 要 |

装完 TrollStore 立刻做一件事：**Install Persistence Helper**（选「提示」或「天气」当替身），否则重启后 TrollStore 可能消失。

---

## 4. 客户：装我们的 App

1. TrollStore → 右上 `+` → 选 `SuperLocator.z2.tipa` → Install；
2. 回桌面打开「超级虚拟定位」；
3. 首次进入点「端上模式」按钮，看状态行：

| 状态文字 | 含义 | 处理 |
| --- | --- | --- |
| DDI 已挂载（端上模式可用） | 正常 | 继续下一步 |
| 包内没有 DDI | 忘了 inject | 让卖家重新给包 |
| copyDevices 返回空 | entitlements 没生效 | 让卖家确认 `ldid -S` 打过 |
| mountImage 失败：… | DDI 形态不对（17.4+ 要 cryptex） | 换 `--variant cryptex` 重打 |

4. 挂载成功后 `DTXLocation.connect()` 返回 true，状态变「端上模式：已连接 · 续命推送 N 次」。

---

## 5. 客户：日常使用（全程无线）

| 想做的事 | 操作 |
| --- | --- |
| 改到某个坐标 | 手动页输入经纬度 → 应用 |
| 沿录好的轨迹走 | 轨迹页选轨迹 → 设速度/循环/抖动 → 开始重放 |
| 沿预设路径走 | 预设路径页选路径 → 开始 |
| 停止、回真实 | 首页「停止模拟」 |
| 换轨迹文件 | 用 App 内导入，或把 plist/JSON 推进 App 容器 |

App 被系统挂起时 `DTXKeepAlive` 每 5 秒重推；手机重启后打开 App 会自动重挂 DDI，**不需要电脑**。

---

## 6. 激活码（发码用）

```bash
# Windows 上，用母台账发码（通用码，任何机器可用）
python work/tools/acttool.py keygen --universal -n 1 --note 客户A

# 绑机码（推荐售卖用，一码一机）
python work/tools/acttool.py keygen --device-hash <客户在 App 里看到的设备码> -n 1 --note 客户A
```

App 端输入码后由 `CodeMath.verify` 本地校验（离线，HMAC 自证），无需服务器。

---

## 7. 常见故障对照

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| TrollStore 装不上 tipa | 包没签名/签名被破坏 | 用 `make_tipa.py` 重打，别用普通 zip 工具改包 |
| 装上闪退 | entitlements 过激进（no-sandbox 与容器冲突） | 先只留 `dvt.simulatelocation` + `platform-application` |
| 位置不变，状态却显示已连接 | 目标 App 走了别的定位源（如百度 SDK 缓存） | 重启目标 App；用系统地图验证 |
| 锁屏一会儿回真实 | App 被挂起 | 设置 → 通用 → 后台 App 刷新 → 允许；`DTXKeepAlive` 已开 |
| 重启后失效 | DDI 掉、App 未启动 | 打开一次 App 即恢复 |
| 17.1+ 装不了 TrollStore | 版本不支持 | 只能盒子/电脑 |

---

## 8. 一句话总结

**卖家做一次包（CI 或 Mac），客户装一次 TrollStore 和 App，之后永久无线、不越狱、不插线。**
唯一的“一次性”成本：15.5–16.6.1 要签一次名，16.7–17.0 要跑一次 TrollRestore。