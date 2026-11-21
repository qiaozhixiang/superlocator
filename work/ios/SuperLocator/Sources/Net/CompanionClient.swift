//
//  CompanionClient.swift
//  iPhone ↔ 电脑伴侣程序（superlocator.py serve）的 TCP 行分隔 JSON 通道。
//
//  为什么是 TCP：iOS App 没有任何 API 能改写系统定位。真正的写入由电脑端通过
//  USB + 开发者服务（DVT simulate-location）完成。App 负责算轨迹/抖动/路径，
//  把每一帧坐标发给伴侣程序，伴侣程序再写给设备。
//

import Foundation
import Network
import Combine

final class CompanionClient: ObservableObject {

    enum State: Equatable {
        case idle, connecting, ready, failed(String)

        var text: String {
            switch self {
            case .idle: return "未连接"
            case .connecting: return "连接中…"
            case .ready: return "已连接"
            case .failed(let msg): return "连接失败：\(msg)"
            }
        }
    }

    @Published var state: State = .idle
    @Published var host: String = UserDefaults.standard.string(forKey: "companion.host") ?? "192.168.1.100"
    @Published var port: Int = UserDefaults.standard.object(forKey: "companion.port") as? Int ?? 47654
    @Published var deviceName: String = ""
    @Published var serverVersion: String = ""
    @Published var lastError: String = ""
    @Published var sentCount: Int = 0
    @Published var licenseEnabled: Bool = false
    @Published var licenseActive: Bool = false
    @Published var licenseSerial: Int = 0
    @Published var licenseMessage: String = ""

    private var connection: NWConnection?
    private var buffer = Data()
    private let queue = DispatchQueue(label: "companion.tcp")

    /// 收到伴侣程序推送的事件（position/status），交给 InjectionSession 显示
    var onEvent: (([String: Any]) -> Void)?

    var isReady: Bool {
        if case .ready = state { return true }
        return false
    }

    // MARK: - 连接

    func connect() {
        disconnect()
        UserDefaults.standard.set(host, forKey: "companion.host")
        UserDefaults.standard.set(port, forKey: "companion.port")

        guard let nwPort = NWEndpoint.Port(rawValue: UInt16(clamping: port)) else {
            state = .failed("端口非法")
            return
        }
        let conn = NWConnection(host: NWEndpoint.Host(host), port: nwPort, using: .tcp)
        connection = conn
        state = .connecting
        buffer.removeAll()

        conn.stateUpdateHandler = { [weak self] newState in
            DispatchQueue.main.async {
                guard let self else { return }
                switch newState {
                case .ready:
                    self.state = .ready
                    self.send(["cmd": "hello", "app": "SuperLocator/1.0"])
                case .failed(let err):
                    self.state = .failed(err.localizedDescription)
                    self.lastError = err.localizedDescription
                case .cancelled:
                    if case .ready = self.state { self.state = .idle }
                default:
                    break
                }
            }
        }
        conn.start(queue: queue)
        receiveLoop(conn)
    }

    func disconnect() {
        connection?.cancel()
        connection = nil
        if case .ready = state { state = .idle }
    }

    // MARK: - 收发

    private func receiveLoop(_ conn: NWConnection) {
        conn.receive(minimumIncompleteLength: 1, maximumLength: 64 * 1024) { [weak self] data, _, isDone, error in
            guard let self else { return }
            if let data, !data.isEmpty {
                Task { @MainActor in self.consume(data) }
            }
            if let error {
                Task { @MainActor in
                    self.lastError = error.localizedDescription
                    if case .ready = self.state { self.state = .failed(error.localizedDescription) }
                }
                return
            }
            if isDone { return }
            self.receiveLoop(conn)
        }
    }

    private func consume(_ data: Data) {
        buffer.append(data)
        while let idx = buffer.firstIndex(of: 0x0A) {
            let lineData = buffer[buffer.startIndex..<idx]
            buffer.removeSubrange(buffer.startIndex...idx)
            guard !lineData.isEmpty,
                  let obj = try? JSONSerialization.jsonObject(with: Data(lineData)) as? [String: Any] else { continue }
            if let version = obj["version"] as? String { serverVersion = version }
            if let dev = obj["device"] as? String, !dev.isEmpty { deviceName = dev }
            if let lic = obj["license"] as? [String: Any] { applyLicense(lic) }
            if obj["needLicense"] as? Bool == true {
                licenseActive = false
                licenseMessage = (obj["error"] as? String) ?? "电脑端要求先激活"
            }
            if obj["cmd"] as? String == "license_activate" {
                licenseMessage = (obj["message"] as? String) ?? ""
                licenseActive = (obj["active"] as? Bool) ?? false
                licenseSerial = (obj["serial"] as? Int) ?? 0
                licenseEnabled = (obj["enabled"] as? Bool) ?? true
                LicenseStore.shared.updateServer(active: licenseActive, serial: licenseSerial, message: licenseMessage)
            }
            onEvent?(obj)
        }
    }

    /// 发送一条命令；未连接时静默丢弃并记录原因
    @discardableResult
    func send(_ payload: [String: Any]) -> Bool {
        var obj = payload
        obj["device"] = CodeMath.deviceId()
        guard let conn = connection else {
            lastError = "未连接伴侣程序"
            return false
        }
        guard let data = try? JSONSerialization.data(withJSONObject: obj) else { return false }
        var line = data
        line.append(0x0A)
        conn.send(content: line, completion: .contentProcessed { [weak self] error in
            if let error {
                Task { @MainActor in self?.lastError = error.localizedDescription }
            }
        })
        sentCount += 1
        return true
    }

    // MARK: - 语义化命令

    private func applyLicense(_ lic: [String: Any]) {
        licenseEnabled = (lic["enabled"] as? Bool) ?? false
        licenseActive = (lic["active"] as? Bool) ?? false
        licenseSerial = (lic["serial"] as? Int) ?? 0
        LicenseStore.shared.updateServer(active: licenseActive, serial: licenseSerial)
    }

    func licenseStatus() { send(["cmd": "license_status"]) }

    func activate(code: String) {
        licenseMessage = "正在校验…"
        send(["cmd": "license_activate", "code": code])
    }

    func setLocation(lat: Double, lng: Double) {
        send(["cmd": "set", "lat": lat, "lon": lng])
    }

    func setJitter(radius: Double, bias: Double, bearing: Double?) {
        var m: [String: Any] = ["cmd": "jitter", "radius": radius, "bias": bias]
        if let bearing { m["bearing"] = bearing } else { m["bearing"] = NSNull() }
        send(m)
    }

    func playTrack(_ track: Track, speed: Double, loop: Bool,
                   radius: Double, bias: Double, bearing: Double?) {
        var payload: [String: Any] = [
            "kind": "track",
            "speed": speed,
            "loop": loop,
            "radius": radius,
            "bias": bias
        ]
        if let bearing { payload["bearing"] = bearing } else { payload["bearing"] = NSNull() }
        if let data = try? JSONEncoder().encode(track),
           let dict = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
            payload.merge(dict) { _, b in b }
        }
        send(["cmd": "play", "payload": payload])
    }

    func playRoute(_ route: PresetRoute, loop: Bool,
                   radius: Double, bias: Double, bearing: Double?) {
        var payload: [String: Any] = [
            "kind": "route",
            "loop": loop,
            "radius": radius,
            "bias": bias,
            "offsetPercent": route.offsetPercent
        ]
        if let bearing { payload["bearing"] = bearing } else { payload["bearing"] = NSNull() }
        if let data = try? JSONEncoder().encode(route),
           let dict = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
            payload.merge(dict) { _, b in b }
        }
        send(["cmd": "play", "payload": payload])
    }

    func pause() { send(["cmd": "pause"]) }
    func resume() { send(["cmd": "resume"]) }
    func stop() { send(["cmd": "stop"]) }
    func requestStatus() { send(["cmd": "status"]) }
}