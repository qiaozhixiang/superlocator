import SwiftUI

/// 激活门：电脑端确认之前，任何「设坐标 / 重放 / 路径」都会被伴侣程序拒绝，
/// 所以先把授权做完再进主界面。
struct ActivationView: View {
    @ObservedObject var client: CompanionClient

    @State private var input: String = ""
    @State private var busy = false
    @State private var note: String = ""

    private var deviceId: String { CodeMath.deviceId() }
    private var store: LicenseStore { LicenseStore.shared }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                VStack(alignment: .leading, spacing: 6) {
                    Text("需要激活码")
                        .font(.system(size: 24, weight: .bold))
                        .foregroundStyle(.white)
                    Text("这台设备首次使用要先激活。激活码由电脑端的 superlocator license keygen 生成；吊销 / 删除在电脑上一改，手机立刻失效。")
                        .font(.system(size: 12.5))
                        .foregroundStyle(Color(white: 0.68))
                        .lineSpacing(2)
                }
                .padding(.top, 8)

                VStack(alignment: .leading, spacing: 10) {
                    Text("本机设备号（发给发码人可做绑定码）")
                        .font(.system(size: 12))
                        .foregroundStyle(Color(white: 0.55))
                    HStack {
                        Text(deviceId)
                            .font(.system(size: 12.5, design: .monospaced))
                            .foregroundStyle(.white)
                            .textSelection(.enabled)
                        Spacer()
                        Button {
                            UIPasteboard.general.string = deviceId
                            note = "已复制设备号"
                        } label: { Image(systemName: "doc.on.doc") }
                    }
                }
                .padding(12)
                .background(RoundedRectangle(cornerRadius: 12).fill(Color(white: 0.12)))

                VStack(alignment: .leading, spacing: 10) {
                    Text("激活码")
                        .font(.system(size: 12))
                        .foregroundStyle(Color(white: 0.55))
                    TextField("XXXXX-XXXXX-XXXXX-XXXXX", text: $input)
                        .textInputAutocapitalization(.characters)
                        .autocorrectionDisabled()
                        .font(.system(size: 15, design: .monospaced))
                        .padding(10)
                        .background(RoundedRectangle(cornerRadius: 10).fill(Color(white: 0.10)))
                        .onChange(of: input) { _, v in
                            let cleaned = CodeMath.pretty(v)
                            if cleaned != v { input = cleaned }
                        }
                    HStack(spacing: 10) {
                        Button {
                            activate()
                        } label: {
                            Text(busy ? "校验中…" : "激活")
                                .frame(maxWidth: .infinity)
                                .padding(.vertical, 11)
                                .background(RoundedRectangle(cornerRadius: 10)
                                    .fill(Color(red: 0.18, green: 0.42, blue: 1.0)))
                                .foregroundStyle(.white)
                        }
                        .disabled(busy || input.isEmpty || !client.state.isReady)

                        Button {
                            client.connect()
                            note = "正在连接电脑端…"
                        } label: {
                            Text("重新连接")
                                .padding(.vertical, 11).padding(.horizontal, 14)
                                .background(RoundedRectangle(cornerRadius: 10).fill(Color(white: 0.16)))
                                .foregroundStyle(.white)
                        }
                    }
                }
                .padding(12)
                .background(RoundedRectangle(cornerRadius: 12).fill(Color(white: 0.12)))

                VStack(alignment: .leading, spacing: 6) {
                    Text(connectionLine).font(.system(size: 12.5)).foregroundStyle(statusColor)
                    if !note.isEmpty { Text(note).font(.system(size: 12)).foregroundStyle(Color(white: 0.6)) }
                    Text("电脑端：python superlocator.py serve --engine lib\n生成码：python superlocator.py license keygen -n 1 --note 你的客户名")
                        .font(.system(size: 11.5, design: .monospaced))
                        .foregroundStyle(Color(white: 0.45))
                        .lineSpacing(2)
                }
                .padding(.top, 2)
            }
            .padding(16)
        }
        .background(Color(red: 0.05, green: 0.07, blue: 0.11).ignoresSafeArea())
        .onAppear {
            client.connect()
            client.licenseStatus()
        }
        .onChange(of: client.licenseActive) { _, active in
            if active {
                store.updateServer(active: true, serial: client.licenseSerial, message: client.licenseMessage)
            }
        }
        .onChange(of: client.licenseMessage) { _, msg in
            if !msg.isEmpty { note = msg }
            busy = false
        }
    }

    private var connectionLine: String {
        switch client.state {
        case .ready: return "电脑端已连接（\(client.host):\(client.port)）· 授权状态：\(client.licenseActive ? "已激活 #\(client.licenseSerial)" : "未激活")"
        case .connecting: return "正在连接电脑端…"
        case .idle: return "未连接电脑端"
        case .failed(let m): return "连接失败：\(m)"
        }
    }

    private var statusColor: Color {
        client.state.isReady ? Color(red: 0.35, green: 0.85, blue: 0.55) : Color(red: 0.95, green: 0.65, blue: 0.3)
    }

    private func activate() {
        let code = CodeMath.clean(input)
        guard CodeMath.parse(code) != nil else { note = "码格式不对：应是 20 位、4 组 5 位"; return }
        guard client.state.isReady else { note = "先连上电脑端才能激活"; return }
        busy = true
        note = "正在让电脑端校验…"
        store.save(code)
        client.activate(code: code)
    }
}

extension CompanionClient.State {
    var isReady: Bool { if case .ready = self { return true } else { return false } }
}