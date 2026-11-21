# 上手卡（挑一条，别全看）

## 先分清两件事

| 你想要的 | 能不能做到 | 怎么做 |
| --- | --- | --- |
| iPhone 上出现一个能用的 App，功能和我们安卓版一样（轨迹库/分组/重放/预设路径/抖动/激活码） | 能 | 走 ipa（CI 出包 + Sideloadly 装）或用网页版（零安装） |
| **不插电脑**也改全机定位，效果等同安卓 | 部分能 | ≤17.0 用 TrollStore 端上注入（TDX）；越狱机型用我们的 deb；其它只能用盒子；纯 App 做不到 |

原因一句话：iOS 沙盒里没有「改系统定位」的 API，唯一通道是开发者服务 `com.apple.dt.simulatelocation`，
必须由外部主机（电脑/盒子）或拿到特权（TrollStore/越狱）的进程调用。这不是实现问题，是平台限制。

---

## 路径 1：Windows 电脑（5 分钟，最省事，所有 iOS 通用）

1. 解压 `SuperLocator-windows.zip` 到 `D:\SuperLocator`
2. 右键 `start-service.bat` → 以管理员身份运行（黑窗口别关）
3. 手机和电脑连同一个 Wi-Fi，手机 Safari 打开窗口里印的地址：
   `http://superlocator.local:47655/`（或窗口里那个 192.168.x.x）
4. 页面顶部粘激活码 → 激活 → 选轨迹/路径 → 开始

排障：先双击 `doctor.bat`，它会把临时目录、授权台账、pymobiledevice3、usbmuxd、端口逐项标 OK/!!。

## 路径 2：定位盒子（一次装好，从此不用电脑，最像“成品”）

树莓派 Zero 2 W / 任意 Debian 12 小主机：

```bash
unzip SuperLocator-box.zip -d ~/stv      # 里面是 box/ 与 companion/
cd ~/stv && sudo bash box/install.sh
```

装完：手机插盒子 USB → 信任 → Safari 开 `http://superlocator.local:47655/`。开机自启、崩溃自动重拉。

## 路径 3：TrollStore（≤17.0，免电脑）

1. 装 TrollStore → 装 TrollFools
2. 注入 `LocSim.dylib` 到目标 App
3. 用 `tools/make_locsim_plist.py` 把轨迹/路径转成 plist，推到手机上

## 路径 4：越狱（checkm8 / 15.0–16.6.1）

`work/ios/oneclick/` 里有一键脚本，`oneclick-jb.bat` 双击即可。DFU 组合键必须人工按。

---

## 常见一句话答

- 「为什么电脑要装苹果驱动？」→ 读设备需要 usbmuxd（Apple Devices / iTunes 自带）。
- 「ipa 为什么 7 天就掉？」→ 免费开发者账号签的 App 只有 7 天，重签或买 $99/年。
- 「激活码能不能离线验？」→ 能，码自带 HMAC，secret 在包里；吊销要重新出包。
- 「手机搜不到 superlocator.local？」→ 同一 Wi-Fi？路由器开了 AP 隔离？防火墙放行了吗？