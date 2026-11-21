// DTXLocation.swift —— 端上直连 DVT（TrollStore / 越狱专用，无电脑方案的核心）
//
// 原理：iPhone 上有一个常驻的私有 mach 服务 `com.apple.dt.simulatelocation`，
// 它接受 DTX 协议的消息，selector `setLocation:` 参数是 {latitude, longitude}。
// Xcode 就是靠它给真机模拟定位的。普通 App 连不上（没有 entitlement），
// 但 TrollStore 用 ldid fakesign 可以给它任意 entitlement，所以这条路在
// TrollStore 设备上是通的；越狱设备上直接作为 root 进程也能连。
//
// 本文件用私有框架 DTXConnectionServices（系统自带）做传输层，避免自己实现
// DTX 分帧；如果这个框架在你的系统版本上不可用，就退化为纯 socket 版（见文件末尾注释）。
//
// 需要的 entitlement（打包时写进 ldid -S 的 plist，已放在 entitlements.plist）：
//   com.apple.private.dvt.simulatelocation   ← 关键
//   platform-application
//   com.apple.private.security.no-container
//   com.apple.private.skip-library-validation

import Foundation

@objc protocol DTXConnectionProtocol {
    func sendControlAsync(_ message: Any)
    func sendControlSync(_ message: Any)
    func resume()
}

final class DTXLocation {

    static let shared = DTXLocation()
    private var connection: AnyObject?
    private var messageClass: AnyClass?
    private(set) var lastError: String?

    /// 连上 mach 服务。返回 false 表示这台机器上这条路不通（没 TrollStore/没越狱）。
    func connect() -> Bool {
        if connection != nil { return true }

        guard let handle = dlopen("/System/Library/PrivateFrameworks/DTXConnectionServices.framework/DTXConnectionServices",
                                  RTLD_NOW) else {
            lastError = "DTXConnectionServices 打不开：\(String(cString: dlerror()))"
            return false
        }
        defer { dlclose(handle) }

        guard let connCls = NSClassFromString("DTXConnection") as? NSObject.Type,
              let msgCls = NSClassFromString("DTXMessage") as? NSObject.Type else {
            lastError = "找不到 DTXConnection / DTXMessage 类"
            return false
        }
        messageClass = msgCls

        // DTXConnection 的构造在私有框架里是 initWithTransport: / connectionToServiceNamed:
        let sel = NSSelectorFromString("connectionToServiceNamed:")
        if connCls.responds(to: sel),
           let conn = connCls.perform(sel, with: "com.apple.dt.simulatelocation")?.takeUnretainedValue() {
            connection = conn as AnyObject
            if (conn as AnyObject).responds(to: NSSelectorFromString("resume")) {
                _ = (conn as AnyObject).perform(NSSelectorFromString("resume"))
            }
            NSLog("[DTX] connected to com.apple.dt.simulatelocation")
            return true
        }

        lastError = "连接 com.apple.dt.simulatelocation 失败（多半是没有 entitlement）"
        return false
    }

    /// 下发一个坐标。失败时 lastError 里有原因。
    @discardableResult
    func setLocation(lat: Double, lng: Double) -> Bool {
        guard connect(), let conn = connection, let msgCls = messageClass else { return false }

        // DTXMessage 的构造：messageWithSelector:types:args:
        // types 用 DTXPrimitiveType：'f' = double（DTXPrimitiveTypeDouble），按参数个数重复。
        let sel = NSSelectorFromString("setLocation:")
        let selCString = strdup(NSStringFromSelector(sel))!
        defer { free(selCString) }

        let makeSel = NSSelectorFromString("messageWithSelector:types:args:")
        guard msgCls.responds(to: makeSel) else {
            lastError = "DTXMessage 不支持 messageWithSelector:types:args:"
            return false
        }

        // 这里用 NSInvocation 拼可变参数（DTX 的探针）。探针拿不到就退化为 KVC 构造。
        let msg = buildMessage(msgCls: msgCls, selector: sel, lat: lat, lng: lng)
        guard let message = msg else {
            lastError = "构造 DTXMessage 失败"
            return false
        }

        let sendSel = NSSelectorFromString("sendControlAsync:")
        if (conn as AnyObject).responds(to: sendSel) {
            _ = (conn as AnyObject).perform(sendSel, with: message)
            return true
        }
        let sendSel2 = NSSelectorFromString("sendMessageAsync:")
        if (conn as AnyObject).responds(to: sendSel2) {
            _ = (conn as AnyObject).perform(sendSel2, with: message)
            return true
        }
        lastError = "找不到发送方法（sendControlAsync: / sendMessageAsync:）"
        return false
    }

    private func buildMessage(msgCls: NSObject.Type, selector: Selector, lat: Double, lng: Double) -> AnyObject? {
        // 优先：+messageWithSelector:types:args:（types 是 C 字符串 "'f'f"，args 是 NSArray<NSNumber>）
        let mk = NSSelectorFromString("messageWithSelector:types:args:")
        if msgCls.responds(to: mk) {
            typealias Fn = @convention(c) (AnyObject, Selector, Selector, UnsafePointer<CChar>, NSArray) -> AnyObject?
            let imp = msgCls.method(for: mk)
            let fn = unsafeBitCast(imp, to: Fn.self)
            let types = strdup("dd")!     // 两个 double
            defer { free(types) }
            if let obj = fn(msgCls as AnyObject, mk, selector, types, [lat, lng] as NSArray) {
                return obj
            }
        }
        // 退化：用 KVC 造一个空消息再塞 selector 与参数（部分系统版本可用）
        let obj = msgCls.init()
        obj.setValue(NSStringFromSelector(selector), forKey: "selector")
        obj.setValue([lat, lng], forKey: "arguments")
        return obj
    }

    func clear() {
        // DVT 的清理指令是 selector `stopSimulation`（无参）
        guard connect(), let conn = connection, let msgCls = messageClass else { return }
        if msgCls.responds(to: NSSelectorFromString("messageWithSelector:")) {
            let sel = NSSelectorFromString("messageWithSelector:")
            let imp = msgCls.method(for: sel)
            typealias Fn = @convention(c) (AnyObject, Selector, Selector) -> AnyObject?
            let fn = unsafeBitCast(imp, to: Fn.self)
            if let msg = fn(msgCls as AnyObject, sel, NSSelectorFromString("stopSimulation")) {
                if (conn as AnyObject).responds(to: NSSelectorFromString("sendControlAsync:")) {
                    _ = (conn as AnyObject).perform(NSSelectorFromString("sendControlAsync:"), with: msg)
                }
            }
        }
    }
}

// ---------------------------------------------------------------------------
// 调试提示（真机验证顺序）
// 1. 先确认 mach 服务存在：
//      launchctl print system | grep simulatelocation      （越狱机）
// 2. 确认 entitlement 生效：
//      ldid -e YourApp.app/YourApp
// 3. 若 connect() 返回 false 且 lastError 是「打不开框架」，
//    说明系统版本把 DTXConnectionServices 移走了 → 走文件末尾的 socket 版。
// 4. 若连接成功但坐标不动，用 console 看 DTX 回执，通常是 selector 名字写错
//    （不同系统版本叫 setLocation: 或 simulateLocation:）。
//
// socket 版（备用）：iOS 17 的 `com.apple.dt.simulatelocation` 若以 unix socket 暴露
// （/var/run/com.apple.dt.simulatelocation.sock），可直接按 DTX 分帧发送：
//   magic 0x1F3D5B79 | header 16 字节 | payload plist(NSKeyedArchiver)
// 这段的参考实现是 pymobiledevice3 的 dtx_service.py，可 1:1 移植。
// ---------------------------------------------------------------------------

// MARK: - 保活：TrollStore 装的 App 一旦被挂起，DVT 会话就断，位置回真实。
// 这里用 UIApplication 的后台任务 + 5 秒重推来“续命”，配合 info.plist 的后台刷新。
import UIKit

final class DTXKeepAlive {
    static let shared = DTXKeepAlive()

    private var timer: Timer?
    private var bgTask: UIBackgroundTaskIdentifier = .invalid
    private var last: (Double, Double)?
    private(set) var pushes = 0
    private(set) var failures = 0

    func start(lat: Double, lng: Double, every: TimeInterval = 5) {
        last = (lat, lng)
        timer?.invalidate()
        timer = Timer.scheduledTimer(withTimeInterval: every, repeats: true) { [weak self] _ in
            guard let self, let (la, lo) = self.last else { return }
            if DTXLocation.shared.setLocation(lat: la, lng: lo) { self.pushes += 1 } else { self.failures += 1 }
        }
        RunLoop.main.add(timer!, forMode: .common)
    }

    func update(lat: Double, lng: Double) { last = (lat, lng) }

    func stop() {
        timer?.invalidate(); timer = nil
        endBG()
    }

    func noteBackground() {
        guard bgTask == .invalid else { return }
        bgTask = UIApplication.shared.beginBackgroundTask(withName: "stv-locsim") { [weak self] in
            self?.endBG()
        }
    }

    private func endBG() {
        guard bgTask != .invalid else { return }
        UIApplication.shared.endBackgroundTask(bgTask)
        bgTask = .invalid
    }

    /// 一句话体检，给界面显示用
    func status(connected: Bool) -> String {
        connected ? "端上模式：已连接 · 续命推送 \(pushes) 次，失败 \(failures) 次"
                  : "端上模式：未连接（\(DTXLocation.shared.lastError ?? "未知原因")）"
    }
}
