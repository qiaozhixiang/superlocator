import Foundation

/// 端上挂载开发者磁盘镜像（DDI）。
///
/// 背景：`com.apple.dt.simulatelocation` 这个 mach 服务由 DDI 提供，不在系统本体里。
/// 平时由宿主的 `pymobiledevice3 mounter auto-mount` 挂载；这里用私有框架
/// MobileImageMounter 在设备本地完成同样的事，从而彻底不依赖电脑。
///
/// 需要 entitlements（见 ondevice/entitlements.plist）：
///   - com.apple.private.mobile_image_mounter
///   - com.apple.private.dvt.simulatelocation（后续连 DTX 用）
///   - platform-application / com.apple.private.security.no-container
///
/// 需要把 DDI 放进 App 包内：ddi/<osVersion>/BuildManifest.plist、Image.dmg、Image.dmg.trustcache
final class DDIMounter {

    static let shared = DDIMounter()

    private var handle: UnsafeMutableRawPointer?
    private(set) var lastError: String = ""
    private(set) var mounted = false

    private typealias MsgSend = @convention(c) (AnyObject, Selector) -> AnyObject?
    private typealias MsgSendObj = @convention(c) (AnyObject, Selector, AnyObject?) -> AnyObject?

    private init() {}

    /// DDI 在包内的目录，按系统主版本号选（找不到就退回 ddi/default）
    static func ddiDir() -> URL? {
        let v = ProcessInfo.processInfo.operatingSystemVersion
        let major = "\(v.majorVersion).\(v.minorVersion)"
        let bundle = Bundle.main.bundleURL
        let candidates = [
            bundle.appendingPathComponent("ddi/\(major)"),
            bundle.appendingPathComponent("ddi/\(v.majorVersion)"),
            bundle.appendingPathComponent("ddi/default")
        ]
        for c in candidates {
            let manifest = c.appendingPathComponent("BuildManifest.plist")
            let dmg = c.appendingPathComponent("Image.dmg")
            if FileManager.default.fileExists(atPath: manifest.path),
               FileManager.default.fileExists(atPath: dmg.path) {
                return c
            }
        }
        return nil
    }

    /// 本地挂载。成功返回 true，并把服务名 `com.apple.dt.simulatelocation` 变成可连接状态。
    @discardableResult
    func mount() -> Bool {
        if mounted { return true }
        lastError = ""

        guard let dir = DDIMounter.ddiDir() else {
            lastError = "包内没有 DDI（应存在 ddi/<版本>/BuildManifest.plist 与 Image.dmg）"
            return false
        }

        let dmgPath = dir.appendingPathComponent("Image.dmg").path
        let trustPath = dir.appendingPathComponent("Image.dmg.trustcache").path
        let cryptexInfoPath = dir.appendingPathComponent("Image.dmg.cryptex_info").path
        let rootHashPath = dir.appendingPathComponent("Image.dmg.root_hash").path
        let hasTrust = FileManager.default.fileExists(atPath: trustPath)
        let isCryptex = FileManager.default.fileExists(atPath: cryptexInfoPath)

        guard let h = dlopen("/System/Library/PrivateFrameworks/MobileImageMounter.framework/MobileImageMounter", RTLD_NOW) else {
            lastError = "MobileImageMounter 框架打不开（系统版本可能不支持）"
            return false
        }
        handle = h

        guard let cls = NSClassFromString("MobileImageMounter") as? NSObject.Type else {
            lastError = "找不到 MobileImageMounter 类"
            return false
        }

        let service = cls.perform(NSSelectorFromString("sharedInstance"))?.takeUnretainedValue() as AnyObject
        let mounter = service

        // 1) 读设备个性化标识（没有这个权限会直接抛）
        var devices: AnyObject?
        let selCopyDevices = NSSelectorFromString("copyDevices")
        if let imp = mounter.method(for: selCopyDevices) {
            typealias F = @convention(c) (AnyObject, Selector) -> AnyObject?
            let f = unsafeBitCast(imp, to: F.self)
            devices = f(mounter, selCopyDevices)
        }
        if devices == nil {
            lastError = "copyDevices 返回空：多半是 com.apple.private.mobile_image_mounter 没生效"
            return false
        }

        // 2) mountImage:imagePath:imageType:options:completion:
        let sel = NSSelectorFromString("mountImage:imagePath:imageType:options:completion:")
        guard let imp = mounter.method(for: sel) else {
            lastError = "MobileImageMounter 没有 mountImage: 方法"
            return false
        }

        // iOS 17.4+/18 的 DDI 是 cryptex 形态（带 cryptex_info + root_hash），
        // imageType 与额外字段都不同；旧形态用 Personalized。
        let imageType = isCryptex ? "Cryptex" : "Personalized"
        var options: [String: Any] = ["ImageType": imageType]
        if hasTrust {
            options["ImageTrustCache"] = trustPath
        }
        if isCryptex {
            options["CryptexInfo"] = cryptexInfoPath
            if FileManager.default.fileExists(atPath: rootHashPath) {
                options["RootHash"] = rootHashPath
            }
        }

        var done = false
        var mountError: String = ""
        let completion: @convention(block) (AnyObject?) -> Void = { result in
            if let result = result as? [String: Any], let err = result["Error"] {
                mountError = "\(err)"
            }
            done = true
        }

        typealias F = @convention(c) (AnyObject, Selector, AnyObject?, AnyObject?, AnyObject?, AnyObject?, AnyObject?) -> Void
        let f = unsafeBitCast(imp, to: F.self)
        f(mounter, sel, devices, dmgPath as AnyObject, imageType as AnyObject, options as AnyObject, completion as AnyObject)

        // 3) 同步等（TrollStore 下没有 runloop 依赖，用信号量兜住超时）
        let deadline = Date().addingTimeInterval(12)
        while !done && Date() < deadline {
            RunLoop.current.run(mode: .default, before: Date().addingTimeInterval(0.1))
        }

        if !done {
            lastError = "mountImage 12 秒无回调（DDI 镜像版本与系统不匹配是常见原因）"
            return false
        }
        if !mountError.isEmpty {
            lastError = "mountImage 失败：\(mountError)"
            return false
        }

        mounted = true
        return true
    }

    func unmount() {
        // DDI 一般不需要手动卸载；重启即清空。这里只复位内部状态。
        mounted = false
    }

    /// 人类可读状态，给 App 界面用
    func status() -> String {
        if mounted { return "DDI 已挂载（端上模式可用）" }
        if lastError.isEmpty { return "DDI 未挂载" }
        return "DDI 未挂载：\(lastError)"
    }
}