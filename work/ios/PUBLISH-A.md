# 方案 A 详细操作：GitHub Actions 编出 ipa / tipa

> 适用：没有 Mac。全程在 Windows 上操作 + 网页点几下。
> 结果：`dist/` 里出现 `SuperLocator-unsigned.ipa` 与 `SuperLocator.trollstore.tipa`（后者已含 DDI 与 entitlements）。
> 首次大约 20 分钟（其中 12–15 分钟是等 CI）。

---

## 0. 前置检查（已在本机实测通过）

```bash
git --version
# git version 2.56.0.windows.2

ssh -T git@github.com
# Hi qiaozhixiang! You've successfully authenticated, but GitHub does not provide shell access.
```

```bash
cd work/ios
python tools/publish.py --dry-run
# 共 83 个文件（DDI 的 17 MB 二进制已排除，CI 会自己下）
```

要点：
- 有 SSH key 就能 **push**，但 GitHub 不允许 push 创建仓库 → 仓库必须先存在（第 1 步，30 秒）。
- 没有 PAT 也能跑完整个流程：CI 产物通过 **Release 免登录下载**（所以仓库要 Public）。

---

## 1. 建仓库（网页，30 秒）

打开 **https://github.com/new**，按下表填：

| 字段 | 值 | 为什么 |
| --- | --- | --- |
| Owner | `qiaozhixiang` | 你的账号 |
| Repository name | `superlocator` | 脚本默认值，换成别的要带 `--repo` |
| Description | 留空 | 无所谓 |
| Visibility | **Public** | Release 资产才能免登录下载 |
| Add a README | **不勾** | 勾了会和首推冲突（需要先 pull） |
| Add .gitignore / license | **不勾** | 同上 |

点 **Create repository**，看到 “Quick setup” 页面就成功了（不用执行它给的命令，我们用自己的脚本）。

---

## 2. 推送 + 等构建 + 拉产物（一条命令）

```bash
cd work/ios
python tools/publish.py --repo qiaozhixiang/superlocator --wait --download dist
```

脚本分 6 个阶段，每阶段你会看到类似输出：

| 阶段 | 做什么 | 耗时 |
| --- | --- | --- |
| 1 collect | 收集 83 个文件（`ci/ios-ipa.yml` → `.github/workflows/`、`ci/gitattributes` → `.gitattributes`、`work/ios/**`） | 1 秒 |
| 2 stage | 在 `work/ios/.publish/repo` 里 `git init -b main` + commit（身份 `SuperLocator Bot`） | 2 秒 |
| 3 push | `git push -u origin main`（SSH，用你的 key） | 5–20 秒 |
| 4 wait | 每 20 秒轮询 Actions 运行状态，打印 `queued → in_progress → completed(success)` | 12–15 分钟 |
| 5 download | 从 `releases/tag/ipa-latest` 取 `.ipa` / `.tipa` 到 `dist/` | 5–10 秒 |
| 6 verify | 打印两个文件的 size 与 sha256 | 1 秒 |

> 如果中途断了：再跑一次同样的命令即可（幂等，已存在会跳过推送、直接等）。

---

## 3. 网页上看什么（可选，用于排错）

- **Actions 页**：`https://github.com/qiaozhixiang/superlocator/actions`
  点最新一次 `ios-ipa`，应看到 14 个步骤，顺序：

  1. 环境（`macos-14`、`xcodegen` 安装）
  2. 生成工程（`xcodegen generate`）
  3. 单元测试（模拟器，`Executed 16 tests`）
  4. 导入 P12 证书（无 secrets 时跳过）
  5. 导入 Provisioning Profile（同上）
  6. 无签名构建 + 打 ipa
  7. 产物指纹（`shasum -a 256`）
  8. 打包 TrollStore tipa（塞 entitlements）
  9. **拉取 DDI 并注入 tipa**（`fetch_ddi.py` → `inject_ddi.py`）
  10. 签名构建 + 导出 ipa（无 secrets 时跳过）
  11. 校验 ipa 结构
  12. 上传产物（artifact）
  13. 发布 Release（`ipa-latest`）

- **Release 页**：`https://github.com/qiaozhixiang/superlocator/releases/tag/ipa-latest`
  应有 `SuperLocator-unsigned.ipa`、`SuperLocator.trollstore.tipa`（可直接下载，不用登录）。

- **Artifacts**：Actions 运行页底部 `SuperLocator-ipa`（zip 包，需登录下载）—— 与 Release 内容相同，二选一。

---

## 4. 本机验收（拿到包先验，别直接发客户）

```bash
cd work/ios
python tools/make_ipa.py --check dist/SuperLocator-unsigned.ipa
# 期望：包名 com.stv.locator / 版本 1.0（1）/ 最低系统 iOS 17.0 / 可执行文件 正常 / 显示名 超级虚拟定位

unzip -l dist/SuperLocator.trollstore.tipa | grep -E "ddi/|SuperLocator.app/$"
# 期望看到 Payload/SuperLocator.app/ddi/17.0/Image.dmg 等 4 条

python -c "
import zipfile,hashlib
for f in ('dist/SuperLocator-unsigned.ipa','dist/SuperLocator.trollstore.tipa'):
    z=zipfile.ZipFile(f); print(f, len(z.namelist()),'条目','坏条目:',z.testzip())
"
```

三条都过 = 包可用。

---

## 5. 装机（两条路，按客户情况选）

**5.1 有开发者账号/愿意 7 天一签**：用 `SuperLocator-unsigned.ipa` 走 Sideloadly（Windows 装 Sideloadly + Apple Devices，填 Apple ID 专用密码）。

**5.2 走 Z2（TrollStore，永久、不插线）**：用 `SuperLocator.trollstore.tipa`
→ AirDrop/微信传手机 → TrollStore `+` → Install（细节见 `Z2-GUIDE.md` 第 4 节）。

---

## 6. 以后每次改代码怎么出包

```bash
cd work/ios
python tools/publish.py --repo qiaozhixiang/superlocator --wait --download dist
```

或者你自己 `git push`（脚本已把仓库初始化在 `work/ios/.publish/repo`，可以直接在里面 commit/push）：

```bash
cd work/ios/.publish/repo
git add -A && git commit -m "update"
git push
```

CI 会自动重跑，Release 的 `ipa-latest` 资产会被覆盖（`gh release upload --clobber`）。

---

## 7. 报错对照（Actions 日志里搜关键词）

| 日志里的字样 | 原因 | 处理 |
| --- | --- | --- |
| `xcodegen: command not found` | 第 1 步安装失败 | 重跑一次；或把 workflow 里 `brew install xcodegen` 放前面 |
| `Unable to find a destination matching` | 模拟器名不匹配（`iPhone 15` 在 macos-14 存在，换 runner 可能没了） | 改 `ci/ios-ipa.yml` 里的 `name=iPhone 15` |
| `error: Signing for "SuperLocator" requires a development team` | 没 secrets 却走了签名分支 | 确认 `BUILD_CERT_P12_BASE64` 为空（无 secrets 时该步应 skip） |
| `Executed 0 tests` | Tests 目录没被 target 收录 | 检查 `project.yml` 的 `SuperLocatorTests` sources |
| `fetch_ddi.py` 403/超时 | GitHub API 限流 | 重跑；或在其后加 `--mirror https://ghfast.top/` |
| `inject_ddi.py: 这不像一个 ipa` | 输入不是 ipa/tipa | 确认上一步产物名 |
| Release 步 `403 Resource not accessible` | 仓库 Settings → Actions → Workflow permissions 不是 Read and write | 改成 Read and write 后重跑 |
| 下载 404 | Release 还没生成（构建失败） | 先看 Actions 是否成功 |

---

## 8. 一次性 vs 每次

| 项目 | 频率 |
| --- | --- |
| 建仓库 | 一次 |
| 装 Sideloadly / Apple Devices | 一次（如果走 Sideloadly） |
| 跑 `publish.py --wait --download` | 每次改版 |
| 客户端装 TrollStore / 装 tipa | 每台设备一次 |

---

## 9. 安全检查（推之前确认）

```bash
# 确认没把私钥/台账/证书推进仓库
cd work/ios && python tools/publish.py --dry-run | grep -iE "keystore|p12|mobileprovision|gh_token|\.pem"
# 期望：无输出
```

`publish.py` 的 `SKIP_PARTS` 已排除 `build/ out/ dist/ __pycache__/ .publish/ .git/ ddi/`，
后缀排除 `.pyc .log .dmg .trustcache` 与 `ddi_index.json`、`BuildManifest.plist`。