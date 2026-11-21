//
//  RootView.swift
//  App 骨架：四个页签（录制 / 轨迹库 / 重放 / 预设路径）+ 连接伴侣程序。
//

import SwiftUI
import Combine
import CoreLocation

// MARK: - 真实定位参考（只用于取起始坐标，不用于注入）

final class LocationProvider: NSObject, ObservableObject, CLLocationManagerDelegate {
    private let manager = CLLocationManager()
    @Published var latest: Coordinate?
    @Published var authorized = false
    @Published var message = "未授权定位"

    override init() {
        super.init()
        manager.delegate = self
        manager.desiredAccuracy = kCLLocationAccuracyBest
        manager.requestWhenInUseAuthorization()
    }

    func refresh() {
        manager.requestLocation()
    }

    func locationManagerDidChangeAuthorization(_ manager: CLLocationManager) {
        let status = manager.authorizationStatus
        authorized = status == .authorizedWhenInUse || status == .authorizedAlways
        message = authorized ? "已授权" : "未授权定位"
        if authorized { manager.requestLocation() }
    }

    func locationManager(_ manager: CLLocationManager, didUpdateLocations locations: [CLLocation]) {
        guard let loc = locations.last else { return }
        latest = Coordinate(lat: loc.coordinate.latitude, lng: loc.coordinate.longitude)
        message = String(format: "真实定位 %.6f, %.6f", loc.coordinate.latitude, loc.coordinate.longitude)
    }

    func locationManager(_ manager: CLLocationManager, didFailWithError error: Error) {
        message = "取定位失败：\(error.localizedDescription)"
    }
}

// MARK: - 根视图

struct RootView: View {
    @StateObject private var client = CompanionClient()
    @ObservedObject private var session = InjectionSession.shared
    @StateObject private var tracks = TrackStore.shared
    @StateObject private var routes = RouteStore.shared
    @StateObject private var location = LocationProvider()

    @StateObject private var licenseStore = LicenseStore.shared
    @State private var tab = 0
    @State private var showConnection = false

    var body: some View {
        Group {
            if licenseStore.activated {
                tabs
            } else {
                ActivationView(client: client)
            }
        }
    }

    private var tabs: some View {
        TabView(selection: $tab) {
            RecordView(tracks: tracks, client: client, location: location)
                .tabItem { Label("录制", systemImage: "record.circle") }
                .tag(0)
            LibraryView(tracks: tracks)
                .tabItem { Label("轨迹库", systemImage: "square.stack.3d.up") }
                .tag(1)
            ReplayView(tracks: tracks, client: client)
                .tabItem { Label("重放", systemImage: "play.circle") }
                .tag(2)
            RouteView(routes: routes, client: client)
                .tabItem { Label("预设路径", systemImage: "point.topleft.down.to.point.bottomright.curvepath") }
                .tag(3)
        }
        .environmentObject(session)
        .environmentObject(client)
        .safeAreaInset(edge: .top) {
            StatusBar(client: client, session: session, showConnection: $showConnection)
        }
        .sheet(isPresented: $showConnection) {
            ConnectionView(client: client)
        }
        .onAppear {
            session.client = client
            client.onEvent = { event in
                if let lat = event["lat"] as? Double, let lon = event["lon"] as? Double,
                   event["event"] as? String == "position" {
                    session.position = Coordinate(lat: lat, lng: lon)
                    session.hasPosition = true
                }
            }
            // 没有电脑时，切到「本机预览」：只在界面里移动，不写设备
            client.connect()
            client.licenseStatus()
        }
    }
}

// MARK: - 顶部状态条

struct StatusBar: View {
    @ObservedObject var client: CompanionClient
    @ObservedObject var session: InjectionSession
    @Binding var showConnection: Bool

    var body: some View {
        HStack(spacing: 8) {
            Circle()
                .fill(client.isReady ? Color.green : Color.orange)
                .frame(width: 8, height: 8)
            Text(client.state.text)
                .font(.caption)
                .foregroundStyle(.secondary)
            Spacer()
            if session.isPlaying || session.isRecording {
                Text(session.statusMessage)
                    .font(.caption2)
                    .lineLimit(1)
                    .foregroundStyle(.blue)
            }
            Button {
                showConnection = true
            } label: {
                Image(systemName: "antenna.radiowaves.left.and.right")
                    .font(.caption)
            }
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 6)
        .background(.bar)
    }
}

// MARK: - 连接伴侣程序

struct ConnectionView: View {
    @ObservedObject var client: CompanionClient
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            Form {
                Section("电脑端伴侣程序地址") {
                    TextField("主机（电脑的局域网 IP）", text: $client.host)
                        .textInputAutocapitalization(.never)
                        .keyboardType(.numbersAndPunctuation)
                    TextField("端口", value: $client.port, format: .number)
                        .keyboardType(.numberPad)
                    Button(client.isReady ? "断开" : "连接") {
                        if client.isReady { client.disconnect() } else { client.connect() }
                    }
                }
                Section("状态") {
                    LabeledContent("连接", value: client.state.text)
                    if !client.serverVersion.isEmpty {
                        LabeledContent("伴侣版本", value: client.serverVersion)
                    }
                    if !client.lastError.isEmpty {
                        Text(client.lastError).font(.caption).foregroundStyle(.red)
                    }
                    LabeledContent("已发送坐标", value: "\(client.sentCount)")
                }
                Section("电脑上要做的事") {
                    VStack(alignment: .leading, spacing: 8) {
                        Text("1. 数据线连上 iPhone，手机上点「信任」")
                        Text("2. iPhone 设置 → 隐私与安全性 → 开发者模式 → 打开并重启")
                        Text("3. 电脑执行：pip install pymobiledevice3")
                        Text("4. 电脑执行：python superlocator.py serve --engine lib")
                        Text("5. 这里填电脑的局域网 IP，端口 47654")
                    }
                    .font(.caption)
                    .foregroundStyle(.secondary)
                }
                Section {
                    Text("iPhone 自身无法改写系统定位，坐标由电脑通过开发者服务写入设备；本 App 负责算轨迹、抖动与路径。")
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                }
            }
            .navigationTitle("连接伴侣程序")
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("完成") { dismiss() }
                }
            }
        }
    }
}

// MARK: - 通用小组件

struct SectionTitle: View {
    let text: String
    var body: some View {
        Text(text)
            .font(.system(size: 15, weight: .semibold))
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.top, 6)
    }
}

struct HintText: View {
    let text: String
    var body: some View {
        Text(text)
            .font(.caption2)
            .foregroundStyle(.secondary)
            .fixedSize(horizontal: false, vertical: true)
    }
}

struct FieldRow: View {
    let title: String
    @Binding var value: String
    var keyboard: UIKeyboardType = .decimalPad
    var placeholder: String = ""

    var body: some View {
        HStack {
            Text(title).font(.subheadline)
            Spacer()
            TextField(placeholder, text: $value)
                .multilineTextAlignment(.trailing)
                .keyboardType(keyboard)
                .frame(maxWidth: 160)
        }
    }
}

struct ActionButton: View {
    let title: String
    var color: Color = .blue
    var enabled: Bool = true
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Text(title)
                .font(.system(size: 15, weight: .semibold))
                .frame(maxWidth: .infinity)
                .padding(.vertical, 11)
                .background(enabled ? color : Color.gray.opacity(0.4))
                .foregroundStyle(.white)
                .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
        }
        .disabled(!enabled)
    }
}

func parseDouble(_ text: String, fallback: Double, min lo: Double, max hi: Double) -> Double {
    let v = Double(text.replacingOccurrences(of: ",", with: ".")) ?? fallback
    return Swift.min(hi, Swift.max(lo, v))
}