# iOS 安装包怎么做、怎么装

## 0. 先说清一件事：iOS 没有「通用安装包」

`.ipa` 本质是 `Payload/SuperLocator.app` 的 zip。但和 Android 的 apk 不同，**同一个 ipa 换台手机就装不上**：

- 里面必须有 `_CodeSignature/`（代码签名）与 `embedded.mobileprovision`（描述文件）；
- 描述文件绑死 **你的 Apple ID 的 Team ID** 与 **这台 iPhone 的 UDID**；
- 用别人的证书签的包，你的手机装不上；没签名的包，Sideloadly / AltStore 会现场用你的账号重签后再装。

另外：`.app` 里的二进制必须由 Xcode（macOS + iOS SDK）编译。**当前构建机是 Windows**，没有 Xcode、
没有 Swift for iOS 工具链，所以「编译」这一步只能在 macOS 上做，或者放到云端 macOS runner 上做 ——
本目录两种流水线都给你备好了，产物直接是可装的 ipa（签名那一步用你自己的 Apple ID，容器里不保存密码）。

---

## 1. 四条路线，按你的手头设备选

| 路线 | 需要 | 有效期 | 时长 | 产物 |
| --- | --- | --- | --- | --- |
| A. Mac + Xcode 直连 | 一台 Mac + 数据线 | 免费账号 7 天 / 付费 1 年 | 5 分钟 | 直接装到手机，不落地 ipa |
| B. GitHub Actions 出 ipa + Sideloadly | Windows + GitHub 账号 + 免费 Apple ID | 7 天（重签即可续） | 15 分钟 | `SuperLocator-unsigned.ipa` |
| C. AltStore（Windows 服务器） | Windows + 免费 Apple ID | 7 天，自动刷新 | 20 分钟 | 同 B，装完自动续签 |
| D. TrollStore | 系统版本在支持列表内 | 永久，不重签 | 5 分钟 | 同 B，装上不受证书限制 |

> 你的需求是「把安装包给我」。能直接给你的文件只有两类：本机自检用的 demo ipa（仅验证打包器，
> 不能装）和面向你账号的流水线。真包必须落在你的账号与设备上，所以下面把三条能出真包的路径写全。

---

## 2. 路线 A：Mac 上一条命令出包并安装

```bash
cd work/ios
TEAM_ID=ABCDE12345 METHOD=development bash build_ipa.sh
```

脚本做的事：`xcodegen generate` → `xcodebuild archive` → `-exportArchive` → `make_ipa.py --check`。
产物 `work/ios/build/export/SuperLocator.ipa`。要 7 天免费签也能出包：

```bash
TEAM_ID=ABCDE12345 METHOD=development CERT_NAME="Apple Development: 你的邮箱 (XXXX)" bash build_ipa.sh
```

装到手机（连数据线，手机点「信任」）：

```bash
xcrun devicectl device install app --device <UDID> work/ios/build/export/SuperLocator.ipa
# 或者
ios-deploy --bundle work/ios/build/export/SuperLocator.app
```

手机端最后一步：设置 → 通用 → VPN 与设备管理 → 开发者 App → 信任你的账号；设置 → 隐私与安全性 →
开发者模式 → 打开 → 重启。

---

## 3. 路线 B：云端出 ipa（Windows 可用，不需要 Mac）

**B1. 把工程推到一个 GitHub 仓库**

```bash
cd work/ios
git init && git add . && git commit -m "SuperLocator iOS"
# 新建一个空仓库后：
git remote add origin git@github.com:<你>/SuperLocator.git
git push -u origin main
```

**B2. 装 workflow**：把 [work/ios/ci/ios-ipa.yml](work/ios/ci/ios-ipa.yml) 复制到仓库根目录的
`.github/workflows/ios-ipa.yml`，push 一次。`Actions → ios-ipa → Run workflow` 手动跑也行。

跑完在本次运行的 `Artifacts` 里下 `SuperLocator-ipa.zip`，解压得到
`SuperLocator-unsigned.ipa`（约 3~6 MB）。

**B3. 用 Sideloadly 装上（Windows）**

1. 装 [Sideloadly](https://sideloadly.io/)（要 iTunes 或 Apple Devices 驱动，跟伴侣程序共用同一套 usbmux 驱动）；
2. iPhone 连电脑，手机上点「信任」；
3. Sideloadly 里 `IPA` 选 `SuperLocator-unsigned.ipa`，`Apple ID` 填你的账号；
4. 会弹密码框：二步验证账号要填 **App 专用密码**（在 [appleid.apple.com](https://appleid.apple.com) → 登录与安全 → App 专用密码 生成，形如 `abcd-efgh-ijkl-mnop`）；
5. 点 `Start`，日志里出现 `Installation successful` 即装好；
6. 手机：设置 → 通用 → VPN 与设备管理 → 开发者 App → 信任；设置 → 隐私与安全性 → 开发者模式 → 打开 → 重启。

Sideloadly 在这一步做的事就是「用你的证书重签 + 把 UDID 写进描述文件」，所以 unsigned ipa 也能装。
免费账号限制：同时最多 3 个自签 App、每 7 天过期一次，重新点一次 Start 就续上（App 内数据不丢）。

**B4. 要出「已签名 ipa」给其他设备**：在仓库 Secrets 里配
`BUILD_CERT_P12_BASE64`、`BUILD_CERT_PASSWORD`、`PROVISIONING_PROFILE_BASE64`、`TEAM_ID`、`PROFILE_NAME`，
workflow 会自动走签名分支，产出 `SuperLocator-signed.ipa`（描述文件里列了 UDID 的设备都能装）。

证书与描述文件怎么导出：

```bash
# Mac 上从钥匙串导出 p12（含私钥），base64 后贴进 secret
security export -k login.keychain -t identities -f pkcs12 -o cert.p12
base64 -i cert.p12 | pbcopy

# 描述文件
ls ~/Library/MobileDevice/Provisioning\ Profiles/
base64 -i ~/Library/MobileDevice/Provisioning\ Profiles/<uuid>.mobileprovision | pbcopy
# PROFILE_NAME 取该文件里的 Name 字段：
security cms -D -i <uuid>.mobileprovision | plutil -extract Name raw -
```

---

## 4. 路线 C：AltStore（装完自动 7 天续签）

1. Windows 装 [AltServer](https://altstore.io/)（同 Sideloadly 的驱动依赖）；
2. iPhone 用 Safari 打开 [altstore.io](https://altstore.io/) 装 AltStore（用它自己的 Apple ID 登录）；
3. AltServer 托盘图标 → `Install AltStore → 你的设备`，输入 Apple ID 与 App 专用密码；
4. 把 `SuperLocator-unsigned.ipa` 放到电脑上，还是 AltServer 托盘 → `Sideload .ipa`（或手机 AltStore → `+` → 从文件选）；
5. 手机 AltStore → `Settings → Refresh After` 打开，插着电、同一 Wi-Fi 时每天自动续签，你就不会遇到 7 天过期。

---

## 5. 路线 D：TrollStore（按系统版本判断，不需要证书）

TrollStore 依赖 CoreTrust 漏洞做永久签名，只在特定系统版本可用。完整的版本区间表、三种安装法
（TrollHelperOTA / TrollInstallerX / TrollRestore）、tipa 产出、Persistence Helper、7 条排障，
都在 [work/ios/TROLLSTORE.md](TROLLSTORE.md)。

最短路径：

```bash
# 1) CI 或 Mac 出包（同时产物 .ipa 与 .tipa）
METHOD=none bash build_ipa.sh
# 2) 传到手机 → 「文件」里点开 tipa → 分享 → TrollStore → Install
```

---

## 6. 打包/校验工具（本机已跑通）

```bash
cd work/ios

# 把 Xcode 产物装成 ipa（可跨机器：Mac 上 archive，拷到 Windows 再打）
python tools/make_ipa.py --archive build/SuperLocator.xcarchive --out SuperLocator.ipa
python tools/make_ipa.py --app build/dd/Build/Products/Release-iphoneos/SuperLocator.app --out SuperLocator.ipa

# 校验任意 ipa：包名、版本、最低系统、可执行文件、签名、描述文件
python tools/make_ipa.py --check SuperLocator.ipa

# 验证打包器本身（造 demo，不用于安装）
python tools/make_ipa.py --selftest
```

`--check` 的实际输出（对 demo 包）：

```
[i] SuperLocator-demo-unsigned.ipa  1.7KB  sha256=432d8611465ed3adda1efc36e98b789e51694cca1576d487de196ec0bc7c9c52
[i] 条目 8 个，Payload 下：SuperLocator.app
[i] 包名 com.stv.locator  版本 1.0（1）  最低系统 iOS 17.0
[i] 显示名 超级虚拟定位
[i] 代码签名 缺失（未签名）  Provisioning 缺失
[!] 发现 2 个问题：
    - 未签名：需要 Xcode / Sideloadly / AltStore 用你的证书重签后才能装
    - 没有 embedded.mobileprovision：真机安装前必须重签
```

判定一个 ipa 是不是「能装的真包」，看三条同时为真：可执行文件在位、`_CodeSignature/CodeResources` 在位、
`embedded.mobileprovision` 在位。

---

## 7. 装不上时的对照表

| 报错 / 现象 | 原因 | 处理 |
| --- | --- | --- |
| `Unable to install "SuperLocator"` | 描述文件没有这台设备的 UDID | 把 UDID 加进描述文件，或走 Sideloadly 重签 |
| `MismatchedApplicationIdentifierEntitlement` | 描述文件的 App ID 与 `com.stv.locator` 不一致 | 在开发者后台建显式 App ID，描述文件绑定它 |
| `device not in provisioning profile` | 同上，UDID 缺失 | 重下发描述文件 |
| `Untrusted Developer` | 装上了但没信任证书 | 设置 → 通用 → VPN 与设备管理 → 信任 |
| `Developer Mode disabled` | 开发者模式没开 | 设置 → 隐私与安全性 → 开发者模式 → 打开并重启 |
| `ApplicationVerificationFailed` | 签名被改坏（例如手工改过 Info.plist） | 重新出包，别手改包内文件 |
| Sideloadly 卡在 90% | usbmux 驱动被 iTunes 版本打断 | 关 iTunes/Apple Devices，换 USB 口重来 |
| 打开就闪退 | 证书过期（7 天到了） | 重签一次；或用 AltStore 自动续签 |
| `maximum number of apps for free development profiles` | 免费账号 3 个自签上限 | 删掉不用的自签 App 再装 |
| 手机上看不到「开发者模式」 | 系统 ≥16 且从未装过开发版 App | 先用 Xcode/Sideloadly 装一次，这个开关才会出现 |
| 装好后定位不动 | 伴侣程序没跑 | 电脑 `python superlocator.py serve --engine lib` |

---

## 8. 装完后的三步连通

1. 手机：允许「定位」「本地网络」，开发者模式已开；
2. 电脑：`python -m pymobiledevice3 mounter auto-mount`，再 `python superlocator.py serve --engine lib --port 47654`；
3. App 顶部天线图标 → 填电脑 IPv4 → 连接 → 先用 `samples/track_campus.json` 试一次重放，
   手机屏幕上出现移动的蓝点、电脑日志出现 `客户端接入` 与坐标帧，就说明整条链路通了。