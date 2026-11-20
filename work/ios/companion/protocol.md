# 通信协议（iPhone App ↔ 电脑伴侣程序）

传输：TCP，默认端口 **47654**，行分隔 JSON（每个对象一行，`\n` 结束，UTF-8）。
App 主动连接电脑（电脑 `superlocator.py serve` 监听 `0.0.0.0:47654`）。

## 握手

电脑在连接建立后立刻发一条：

```json
{"ok": true, "event": "hello", "version": "1.0.0", "device": "00008030001A2B3C4D"}
```

App 随后发：

```json
{"cmd": "hello", "app": "SuperLocator/1.0"}
```

## App → 电脑

| 命令 | 字段 | 说明 |
| --- | --- | --- |
| `set` | `lat`, `lon` | 设置一次坐标（App 自己算好抖动后发这个，10 Hz） |
| `jitter` | `radius`, `bias`, `bearing`（可为 `null`） | 让电脑端自己算抖动（电脑端播放时用） |
| `play` | `payload`：轨迹或路径对象 + `speed`/`loop`/`radius`/`bias`/`bearing`/`offsetPercent` | 由电脑端按时间轴播放（App 退出前台也能继续） |
| `pause` / `resume` / `stop` | — | 控制播放 |
| `status` | — | 取一次状态 |
| `ping` | — | 心跳 |

`payload.kind` 为 `"track"` 时按轨迹播放，为 `"route"` 时按预设路径播放；两种对象的字段与 iOS/Android 的 JSON 完全一致（见 README「数据格式」）。

## 电脑 → App

| 事件 | 字段 | 说明 |
| --- | --- | --- |
| `hello` | `version`, `device` | 握手（连接建立即发） |
| `position` | `lat`, `lon`, `baseLat`, `baseLon`, `progress`, `speed`, `segment`, `loops`, `pushes`, `jitter`, `error` | 每帧推送，App 用它更新「当前注入坐标」与进度 |
| 命令回执 | `ok`, `cmd`, 可选 `error`/`desc` | 对每条命令的应答 |

示例（一帧推送）：

```json
{"event":"position","mode":"route","lat":36.710412,"lon":117.021988,"baseLat":36.710398,"baseLon":117.021971,"progress":0.4123,"speed":1.74,"segment":2,"loops":0,"pushes":418,"jitter":"半径 20m · 偏向92° · 权重 55%","error":""}
```

## 兼容性

- 未知命令返回 `{"ok": false, "error": "unknown cmd xxx"}`，连接不断开。
- `lat`/`lon` 使用 WGS-84，与 `CLLocation` 一致；中国大陆的地图显示偏移由 MapKit/苹果地图自行处理，**不要**在协议层做 GCJ-02 转换。
- 一帧约 90 字节，10 Hz 下约 1 KB/s，Wi-Fi 与 USB 网卡共享都够用。USB 直连时也可以把电脑的 `usbmux` 网卡地址当主机（见 README 的「USB 共享网络」一节）。