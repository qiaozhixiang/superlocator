# iOS 安装包构建方式 2：GitHub Actions 出 ipa + Sideloadly 签名装机

> 一句话：让 GitHub 的 macOS 服务器替你编译出 `SuperLocator-unsigned.ipa`，下载后用 Sideloadly 用你自己的 Apple ID 签名装进 iPhone。
> 不需要 Mac、不需要 Xcode、不需要付费开发者账号。装完后 App 有效期 **7 天**，到期重复第 6 步即可。

---

## 0. 前置条件

| 项 | 要求 |
| --- | --- |
| GitHub 账号 | 免费即可（Actions 对公开仓库不限量；私有仓库每月 2000 分钟，本工程约 9 分钟/次） |
| 电脑 | Windows / macOS / Linux 都行（Sideloadly 支持 Win + macOS） |
| iPhone | iOS 17.0+；需能连数据线；首次要开「开发者模式」 |
| Apple ID | 免费账号即可；**必须生成 App 专用密码**，不能直接用登录密码 |
| 磁盘 | 下载的 ipa 约 1–3 MB，Sideloadly 安装包约 90 MB |

---

## 1. 把代码放进仓库（三选一）

### 1.1 网页上传（零工具，最省事）

1. 打开 <https://github.com/new>，Repository name 填 `superlocator`，可见性选 **Public**（公开仓库的 Release 才能免登录下载），**不要**勾 README / .gitignore / License，点 Create repository。
2. 本地解压 `SuperLocator-repo.zip`（本目录里就有），得到 `.github/`、`work/`、`README.md` 等。
3. 在仓库页点 **Add file → Upload files**，把解压出来的**内容**（不是压缩包本身）整体拖进去，Commit changes。
4. 确认仓库根目录能看到 `.github/workflows/ios-ipa.yml`（GitHub 有时会隐藏点开头目录，用 `https://github.com/<你>/superlocator/tree/main/.github/workflows` 直接看）。

### 1.2 一条命令推上去（仓库已存在，用 SSH）

```bash
cd work/ios
python tools/publish.py --repo <你的用户名>/superlocator --wait --download dist
```

`publish.py` 会：打包到 `.publish/repo` → `git init -b main` → commit → `git push git@github.com:<你的用户名>/superlocator.git` → 轮询 Actions → 结束后把 `.ipa`/`.tipa` 下载到 `dist/`。

### 1.3 全自动建仓（需要 PAT）

```bash
set GITHUB_TOKEN=ghp_xxx          # 需要 repo + workflow 权限
python tools/publish.py --repo <你的用户名>/superlocator --wait --download dist
```

`ensure_repo()` 会先 `GET /repos/...`，不存在就 `POST /user/repos` 建一个公开仓库，再推代码、等构建、下产物。

---

## 2. 触发构建

- **自动**：`push` 到 `main` 且改动命中 `work/ios/**` 或 `.github/workflows/ios-ipa.yml` 就会跑。
- **手动**：仓库页 → **Actions** → 左侧 `ios-ipa` → 右侧 **Run workflow** → Run。

一次运行的 12 个步骤：环境（xcodebuild + `brew install xcodegen`）→ 生成工程 → **单元测试（模拟器，16 个用例）** → （可选）导入 P12 / Provisioning → 无签名构建 + 打 ipa → 产物指纹 → （可选）签名导出 → 发布 Release → 上传 artifact。

> 没有配置任何 secrets 时，走的是「无签名构建」分支，产出 `SuperLocator-unsigned.ipa` 与 `SuperLocator-unsigned.tipa`——这正是 Sideloadly 需要的输入。

---

## 3. 下载 ipa

两种入口，内容一样：

| 入口 | 路径 | 是否需要登录 |
| --- | --- | --- |
| Artifacts | Actions → 本次运行 → 页面底部 **Artifacts** → `SuperLocator-ipa` | 需要 GitHub 登录 |
| Release | `https://github.com/<你>/superlocator/releases/tag/ipa-latest` → `SuperLocator-unsigned.ipa` | **公开仓库免登录** |

产物旁边会打印 `sha256(ipa): …`，与本机对比：

```powershell
certutil -hashfile SuperLocator-unsigned.ipa SHA256
```

---

## 4. 准备 Sideloadly 与 Apple ID 专用密码

1. 下载 Sideloadly：<https://sideloadly.io/>（Windows 版 `sideloadly_*.exe`），安装时若弹「未知发布者」点「更多信息 → 仍要运行」。
2. 生成 App 专用密码：<https://appleid.apple.com/> → 登录 → **登录与安全** → **App 专用密码** → 生成 → 名字填 `sideloadly` → 得到 `xxxx-xxxx-xxxx-xxxx`，复制保存（只显示一次）。
3. iPhone 上：**设置 → 隐私与安全性 → 开发者模式 → 打开 → 重启 → 确认打开**（iOS 16+ 必须，否则装完点不开）。

---

## 5. 用 Sideloadly 装机

1. 数据线连 iPhone，解锁，点「信任此电脑」，输入锁屏密码。
2. 打开 Sideloadly，顶部 **iOS Device** 应自动出现你的设备名（没有就点刷新或换 USB 口）。
3. 把 `SuperLocator-unsigned.ipa` 拖进 **IPA 文件**框（或点文件夹图标选）。
4. **Apple ID** 填你的邮箱；**Password** 填刚才那条 App 专用密码。
5. 点 **Start**。若账号开了二次验证，会弹窗要 6 位验证码，输入后继续。
6. 进度条走完显示 `Done`，桌面上出现「超级虚拟定位」。
7. 首次打开若提示「不受信任的开发者」：**设置 → 通用 → VPN与设备管理 → 开发者 App → 你的 Apple ID → 信任**。
8. 打开 App → 激活页 → 输入激活码（母台账里的 `01BYG-X2PB9-AMHP6-CWJWM` 之类）→ 进入四页签。

---

## 6. 7 天到期怎么办

免费签名 **7 天**失效，图标变灰/点开闪退，重跑一遍即可（数据不丢，App 沙盒保留）：

- 简单：Sideloadly 里再点一次 Start（同一个 ipa，同一个 Apple ID），覆盖安装。
- 自动：装 **AltStore**（同一 Apple ID 登录），添加本 ipa 为源，它会在后台每 7 天续签（需电脑与手机同一 Wi-Fi 且 AltServer 常驻）。
- 永久（不需 Apple ID）：走 TrollStore 路线，见 `TROLLSTORE.md`；本 workflow 同时产出的 `.tipa` 就是给它的。

---

## 7. 免费账号的硬限制

| 限制 | 值 | 规避 |
| --- | --- | --- |
| 签名有效期 | 7 天 | 见第 6 步 |
| 同时安装的自签 App | 3 个 | 卸掉不用的 |
| 每年可注册设备数 | 10 台 | 别频繁换机 |
| Bundle ID 唯一性 | 同一 App ID 只能被一个证书签名 | 冲突就改 `BUNDLE_ID`（见下） |

改 bundle id（例如系统里已有别人签过的 `com.stv.locator`）：

```bash
# 方式一：workflow 里改
env:
  BUNDLE_ID: com.stv.locator2

# 方式二：project.yml 里改 PRODUCT_BUNDLE_IDENTIFIER
```

改完重新 push，CI 会出新包；注意 App 会变成「另一个 App」，旧的数据/激活状态不继承。

---

## 8. 常见报错对照

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| Actions 里 `xcodegen: command not found` | runner 镜像变了 | 确认「环境」步骤里有 `brew install xcodegen`；或改 `runs-on: macos-15` |
| `Executed 16 tests, with 0 failures` 之前就失败 | 模拟器名不匹配 | 把 `iPhone 15` 改成 runner 上存在的机型（`xcrun simctl list devices available`） |
| Sideloadly `Failed to fetch app` | ipa 不完整 / 网络 | 重新下载，比对 sha256 |
| `Unable to verify app` / 图标点开闪退 | 证书过期或未信任 | 重签 + 设置里信任开发者 |
| `AMFI: code signature invalid` | 装的是未签名 ipa | 必须经 Sideloadly 签过再装 |
| `This app is not supported on this device` | 架构/最低系统 | 本工程要求 iOS 17.0+；iOS 16 需把 deployment target 降级并去掉 iOS17 Map API |
| Sideloadly 卡 `Generating...` 很久 | Apple 服务器慢 | 等 3–5 分钟；换网络重试 |
| `Maximum number of apps for free development profiles reached` | 免费账号 3 个上限 | 删掉旧的自签 App |
| 装完桌面没图标 | 描述文件没装完 | 重新 Start，留意 Sideloadly 日志最后一行 |

---

## 9. 我可以直接替你跑完这段

仓库建好（哪怕是空的公开仓库）之后：

```bash
cd work/ios
python tools/publish.py --repo <你>/superlocator --wait --download dist
```

跑完 `dist/` 里就躺着 `SuperLocator-unsigned.ipa` + `.tipa`，你只需要做第 4、5 步（Sideloadly 签名装机）。