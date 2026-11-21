import Foundation

/// 激活码格式与串号解析（与 Android / 电脑端同一套 Crockford-Base32 编码）。
/// 注意：iOS 侧**不保存 secret**——密钥只在电脑端台账里，码的合法性由电脑端回执决定，
/// 这样吊销 / 删除码在电脑上一改就生效，手机端连重新打包都不用。
enum CodeMath {
    static let alphabet = Array("0123456789ABCDEFGHJKMNPQRSTVWXYZ")
    static let maxSerial = 1023

    static func clean(_ input: String) -> String {
        input.uppercased().filter { alphabet.contains($0) }
    }

    /// 20 个字符 = 100 bit：高 10 bit 串号，低 90 bit 是 MAC
    static func parse(_ code: String) -> (serial: Int, mac: Int)? {
        let c = clean(code)
        guard c.count == 20 else { return nil }
        var v = 0
        for ch in c {
            guard let i = alphabet.firstIndex(of: ch) else { return nil }
            v = (v << 5) | i
        }
        let serial = v >> 90
        guard (1...maxSerial).contains(serial) else { return nil }
        return (serial, v & ((1 << 90) - 1))
    }

    static func serial(of code: String) -> Int { parse(code)?.serial ?? 0 }

    /// 展示成 4 组 × 5 位
    static func pretty(_ code: String) -> String {
        let c = clean(code)
        guard c.count == 20 else { return c }
        return stride(from: 0, to: 20, by: 5).map { i -> String in
            let a = c.index(c.startIndex, offsetBy: i)
            let b = c.index(a, offsetBy: 5)
            return String(c[a..<b])
        }.joined(separator: "-")
    }

    static func deviceId() -> String {
        let key = "stv_device_id"
        if let v = UserDefaults.standard.string(forKey: key) { return v }
        let v = UUID().uuidString.replacingOccurrences(of: "-", with: "").lowercased()
        UserDefaults.standard.set(v, forKey: key)
        return v
    }
}

/// 授权状态：本机只判格式，放行权在电脑端（serverActive）。
final class LicenseStore: ObservableObject {
    static let shared = LicenseStore()

    @Published private(set) var code: String = ""
    @Published private(set) var serial: Int = 0
    @Published private(set) var serverActive: Bool = false
    @Published private(set) var serverMessage: String = ""

    private let key = "stv_license_code"

    init() {
        code = UserDefaults.standard.string(forKey: key) ?? ""
        serial = CodeMath.serial(of: code)
    }

    var wellFormed: Bool { !code.isEmpty && CodeMath.parse(code) != nil }

    /// 放行条件：格式合法 + 电脑端确认已激活
    var activated: Bool { wellFormed && serverActive }

    func save(_ raw: String) {
        code = CodeMath.clean(raw)
        serial = CodeMath.serial(of: code)
        UserDefaults.standard.set(code, forKey: key)
    }

    func updateServer(active: Bool, serial: Int, message: String = "") {
        serverActive = active
        if serial > 0 { self.serial = serial }
        if !message.isEmpty { serverMessage = message }
    }

    func clear() {
        code = ""
        serial = 0
        serverActive = false
        UserDefaults.standard.removeObject(forKey: key)
    }
}