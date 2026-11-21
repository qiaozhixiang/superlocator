# 越狱方案（含「一键」能做到哪一步）

## 一、先认清一个边界

**越狱不能被「内置成一个功能按钮」。** 越狱的本质是拿到内核读写权限（exploit + 内核补丁），
每一代系统都要对应的漏洞链，这是攻防团队几个月的活儿。所以任何声称「App 里点一下就把
任何 iPhone 越狱」的产品，要么只支持特定老系统，要么用的是别人的现成漏洞链。

能做到的「一键」是：**把检测、下载、推装、启动、装插件、写配置、重启桌面这 7 步串成一条命令**，
只剩「checkm8 机型按 DFU 组合键」和「exploit 由现成工具提供」这两处绕不开。

## 二、按机器选方案（照这个表走）

| 芯片 | 机型 | 系统 | 工具 | 是否必须电脑 |
| --- | --- | --- | --- | --- |
| A5–A11（checkm8） | iPhone 5s–X、同代 iPad | 12–17.x | **palera1n**（15+ 用 rootless） | 是（跑一次，DFU 人工） |
| A12–A16 | iPhone XS–14、同代 iPad | 15.0–16.6.1 | **Dopamine**（rootless，手机上点一下） | 装的时候一次，之后不要 |
| A12+ | 同上 | 17.0 | **TrollStore + TrollFools**（按 App 注入，不是越狱） | 否 |
| A12+ | 同上 | 17.1 及以上 | 无公开越狱 | 只能走盒子方案 |

补充：
- Dopamine 若设备已有 TrollStore（≤17.0），可以直接在手机上装它，全程不用电脑；
- palera1n 的 rootless 支持到 17.x，但每次开机是「半绑定」——重启后要重新跑一次；
- 16.x 还有 Serotonin 这类半越狱（TrollStore + 注入），稳定性一般，不建议卖给客户。

## 三、具体步骤

### A. palera1n（checkm8 机型）

```bash
# Linux / macOS；Windows 用 WSL2
bash -c "$(curl -fsSL https://raw.githubusercontent.com/palera1n/palera1n/main/palera1n.sh)"
palera1n -l          # rootless
palera1n -f          # rootful（老系统用）
```

手机会要求进 DFU，只能人工按：

1. 按住「音量下 + 电源」10 秒；
2. 松开电源键，继续按住音量下 5 秒；
3. 屏幕黑掉即进入 DFU，脚本自动接管。

### B. Dopamine（A12–A16，15.0–16.6.1）

```bash
# 手机已有 TrollStore：直接把 tipa 推上去装
python -m pymobiledevice3 apps install Dopamine.tipa
```

然后在手机上打开 Dopamine → 点 **Jailbreak** → 等重启 → 桌面出现 Sileo，rootless 根在 `/var/jb`。

### C. TrollStore + TrollFools（17.0，不越狱也能注入）

1. 装 TrollStore（按系统版本选 TrollHelperOTA / TrollInstallerX / TrollRestore）；
2. 装 TrollFools；
3. 选目标 App → 注入我们的 `LocSim.dylib` → 只对该 App 生效。

### D. 越狱完之后装我们的插件

```bash
scp LocSim.deb root@<手机IP>:/var/mobile/
ssh root@<手机IP> "dpkg -i /var/mobile/LocSim.deb && killall -9 SpringBoard"
# 下发一条路径
python3 tools/make_locsim_plist.py route.json -o /tmp/l.plist
scp /tmp/l.plist root@<手机IP>:/var/mobile/Library/Preferences/com.stv.locsim.plist
ssh root@<手机IP> "killall -HUP backboardd"
```

## 四、我已经写好的「一键」脚本

`work/ios/oneclick/`

| 文件 | 用途 |
| --- | --- |
| `jb.sh` | Linux/macOS/WSL2：检测机型版本 → 选方案 → 下载/推装/引导 → 装 deb/ipa |
| `jb.ps1` | Windows：同上，自动装 pymobiledevice3、下载 Dopamine、WSL 调 palera1n |
| `oneclick-jb.bat` | 双击即跑 `jb.ps1 -Run`（给客户用，不用教他开 PowerShell） |

用法：

```bash
./jb.sh                 # 只检测 + 出方案（安全）
./jb.sh --run --deb LocSim.deb
```

```powershell
.\jb.ps1 -Run -Deb .\LocSim.deb
```

已验证：`bash -n` 通过、PowerShell 解析通过（必须存成 UTF-8 BOM，否则 Windows PowerShell 会把中文读成乱码导致语法错误——这个坑已经踩过并修好）、无设备时给出明确提示而不是卡住。

## 五、一键的真实边界（写进你的产品说明，别让客户误解）

| 步骤 | 能否自动化 |
| --- | --- |
| 识别机型 / 系统 / 选工具 | ✅ |
| 下载越狱工具 | ✅ |
| 推装到手机 | ✅ |
| 启动越狱流程 | ✅ |
| **checkm8 进 DFU** | ❌ 硬件级，必须人工按键 |
| **exploit 本身** | ❌ 必须用现成工具（palera1n / Dopamine） |
| 装我们的插件 + 写配置 + 重启桌面 | ✅ |
| 免越狱（17.1+） | ❌ 只能卖盒子 |

## 六、产品化建议

1. **越狱版**定位「技术玩家」：卖 deb + 一键脚本，发货即一个 zip（`LocSim.deb` + `jb.sh` + `jb.ps1` + `一键.txt`）；
2. **盒子版**定位「普通用户」：所有机型都能用，不需要越狱；
3. 两个版本共用同一套激活码与轨迹格式，客户换设备不用重买。

## 七、风险提示（给客户的一句话就够）

系统升级会清掉越狱；palera1n 半绑定意味着重启要重越；苹果修漏洞后新系统就没有这条路了。
所以卖越狱版要明确写「只支持 xx 系统及以下」，卖盒子版没有这个问题。