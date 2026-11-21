# 激活码授权（Android APK + iOS App / 网页版）

三条链路共用一套码：**同一份 secret、同一套 Crockford-Base32 编码、同一套 HMAC-SHA256 规则**。
Java（APK 内）、Python（电脑端 / acttool）、Swift（iOS 界面显示与格式校验）三处已对齐。

## 一、码的结构

```
payload(100 bit) = serial(10 bit, 1..1023)  |  mac(90 bit)
mac = HMAC-SHA256(secret, scope + serial_be16) 前 12 字节 → 右移 6 位 → 90 bit
scope = "U"                  → 通用码（换机也能用）
      = "D" + deviceHash     → 设备绑定码（换机失效）
deviceHash(Android) = sha256(androidId + "|" + Build.FINGERPRINT)[:16]
```

100 bit → 20 个字符，字母表 `0123456789ABCDEFGHJKMNPQRSTVWXYZ`（无 I/L/O/U，避免看错），
显示成 4 组 × 5 位：`01C6S-H94W6-DFR0T-N95C2`。

## 二、Android：码烧进 APK，`acttool` 管理与随时构建

```bash
cd work
python tools/acttool.py init                                  # 建台账 work/license/ledger.json（只在本地）
python tools/acttool.py keygen --universal -n 2 --note 首发     # 通用码 ×2
python tools/acttool.py keygen --device-hash 3f1c...e9 -n 1 --note 张三-iPhone   # 绑定码
python tools/acttool.py list                                   # 看所有码、状态、备注
python tools/acttool.py revoke --serial 2                      # 吊销（下次 build 生效）
python tools/acttool.py unrevoke --serial 2
python tools/acttool.py delete --serial 2                      # 删除记录（码彻底报废）
python tools/acttool.py verify --code 01C6S-H94W6-DFR0T-N95C2   # 单码校验
python tools/acttool.py build                                  # bake → javac → dex → apktool → 签名 → out/
```

`build` 每一步都会打印产物路径与 sha256；产物默认落 `work/out/SuperVirtualLocation-3.2-activated-signed.apk`。
`bake` 会把 **secret + 吊销列表 + 已发码序号** 写进 `dec/assets/license.json`，**不写明文码**，
所以 APK 被反编译也拿不到能自己造码的 secret（secret 在 APK 里只用于校验，且与台账同一份）。

APK 侧行为：
- 桌面图标只有 `com.stv.locator.license.ActivateActivity` 一个入口（原 SplashActivity 的 MAIN/LAUNCHER 已移除）；
- 激活页显示本机设备号（可复制）、输入框、激活按钮；
- 激活状态写 `SharedPreferences("stv_license")`，**每次启动都重新验签**，手改 XML 会被判无效；
- 未激活时从抽屉进 `TrackHubActivity` 也会被拦回激活页。

## 三、iOS：secret 不进手机，电脑端做授权中心

iOS 沙盒改不了系统定位，写坐标本来就靠电脑伴侣程序，所以把「激活」也放在电脑端最合适：

```
iPhone App / 网页版  --(TCP 47654, 行分隔 JSON, 带 device 字段)-->  superlocator.py serve
                                                                    ├─ Ledger（secret 只在 PC）
                                                                    └─ DVT simulate-location（写坐标）
```

- App 把码和本机 `device`、`deviceHash` 发过去 → PC `Ledger.activate()` 回 `{ok, serial, active}`；
- 每条 `set / jitter / play / stop / pause / resume` 前，PC 都**回台账重算一次**：
  吊销（`revoke`）或删除（`delete`）**立刻**让手机端失效，不用重打包、不用重启服务；
- 手机端不存 secret（`License.swift` 只做 20 位格式校验与串号解析），所以逆向 App 也造不出码。

电脑端命令：

```bash
cd work/ios/companion
python superlocator.py license init
python superlocator.py license keygen -n 2 --note "iOS 首发"
python superlocator.py license list
python superlocator.py license revoke --serial 1
python superlocator.py license delete --serial 1
python superlocator.py license devices           # 哪台设备用了哪个码
python superlocator.py serve --engine lib        # 起来了就带授权门；--no-license 可关
```

网页版（iPhone Safari，不装任何东西）自带授权条：打开 `http://<电脑IP>:47655/`，
顶部输入框填码 → 激活；未激活时所有写入命令会被电脑端拒绝并回显原因。

## 四、自检

```bash
cd work
python tools/test_license.py        # Java ↔ Python 21 条向量 + 7 条边界 + acttool 命令流
cd work/ios
python tools/test_licensing.py      # TCP/HTTP 两道门 17 项（含吊销/删除即时生效）
python tools/test_web.py            # 网页版 12 项（JS 语法/页面/命令通道）
python tools/test_exe.py            # 打包后的 exe 21 项
```

## 五、一套码管两端（母台账同步）

`work/license/ledger.json` 是**母台账**（acttool 发码）。电脑端把它整表同步过来，两边认同一批码：

```bash
cd work/ios/companion
python superlocator.py license import --from ../../license/ledger.json
```

输出 `已同步母台账：… secret = bf20b10ec746… 码 2 个 / 吊销 0 个`，随后 `license list` 看到的就是 acttool 发的码。
acttool 里吊销/删除后，再跑一次 `license import` 即可让手机端同步失效（不重打包）。

## 六、换 secret（谨慎）

`acttool init` 只在首次建台账时生成 secret。要换：

```bash
python tools/acttool.py init --force        # 新 secret，旧码全部作废
python tools/acttool.py build               # 重新烧进 APK
cd work/ios/companion && python superlocator.py license init --force   # 电脑端也换
```

两边 secret **必须一致**才能互相认码；换完把旧码全部回收，否则用户手里会留下一批「只在旧包里有效」的码。