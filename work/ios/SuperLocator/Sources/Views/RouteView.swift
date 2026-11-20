//
//  RouteView.swift
//  预设路径：地图选节点 → 节点顺序连成路径 → 沿路径位移；
//  每段可单独设速（节点满速 0 表示跟随全局）；「速度偏移量」决定每段速度区间。
//

import SwiftUI

struct RouteView: View {
    @ObservedObject var routes: RouteStore
    @ObservedObject var client: CompanionClient
    @EnvironmentObject var session: InjectionSession

    @StateObject private var engine = RouteEngine()
    @StateObject private var location = LocationProvider()

    @State private var name = "预设路径"
    @State private var nodes: [RouteNode] = []
    @State private var globalSpeed = "1.4"
    @State private var offsetPercent = "20"
    @State private var loop = true
    @State private var showMapPicker = false
    @State private var selectedRouteId = ""
    @State private var message = ""
    @State private var editingSpeeds: [String] = []

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    TrackPreviewView(track: previewTrack,
                                     base: session.hasPosition ? session.position : nil,
                                     injected: session.hasPosition ? session.position : nil,
                                     progress: session.progress,
                                     offsetMeters: 0)
                        .frame(height: 180)
                        .listRowInsets(EdgeInsets(top: 6, leading: 6, bottom: 6, trailing: 6))
                    HintText(text: "灰线是节点连成的路径；开始后红点就是当前注入位置。")
                }

                Section("路径") {
                    TextField("路径名", text: $name)
                    HStack {
                        Button {
                            showMapPicker = true
                        } label: {
                            Label("在地图上选点", systemImage: "map")
                        }
                        Spacer()
                        Button("清空节点", role: .destructive) {
                            nodes.removeAll(); editingSpeeds.removeAll()
                        }
                        .disabled(nodes.isEmpty)
                    }
                    Text(nodes.isEmpty ? "还没有节点（至少 2 个）" :
                            "\(nodes.count) 个节点 · \(max(0, nodes.count - 1)) 段 · \(Int(totalMeters().rounded())) m")
                        .font(.caption).foregroundStyle(.secondary)
                }

                if !nodes.isEmpty {
                    Section("节点与每段速度") {
                        ForEach(Array(nodes.enumerated()), id: \.offset) { idx, node in
                            HStack(spacing: 8) {
                                Text("\(idx + 1)").font(.caption).frame(width: 18)
                                VStack(alignment: .leading, spacing: 1) {
                                    Text(String(format: "%.6f, %.6f", node.lat, node.lng))
                                        .font(.caption).monospacedDigit()
                                    Text(idx == 0 ? "起点" : "到本节点这一段")
                                        .font(.system(size: 9)).foregroundStyle(.secondary)
                                }
                                Spacer()
                                TextField("全局", text: bindingForSpeed(idx))
                                    .keyboardType(.decimalPad)
                                    .multilineTextAlignment(.trailing)
                                    .frame(width: 58)
                                    .font(.caption)
                                Button {
                                    nodes.remove(at: idx)
                                    editingSpeeds.remove(at: idx)
                                } label: {
                                    Image(systemName: "xmark.circle.fill").foregroundStyle(.red.opacity(0.7))
                                }
                                .buttonStyle(.plain)
                            }
                        }
                    }
                }

                Section("速度") {
                    FieldRow(title: "全局速度（m/s）", value: $globalSpeed, placeholder: "1.4")
                    FieldRow(title: "速度偏移量（%）", value: $offsetPercent, placeholder: "20")
                    HintText(text: "每 2.5 秒按 ±偏移量 重采一次段速度：实际速度 = 段基准速度 ×(1 ± 偏移)。节点速度栏留空即跟随全局。步行 1.2~1.6，骑行 4~6，电动车 7~10。")
                }

                Section("控制") {
                    Toggle("循环（到终点后从头再来）", isOn: $loop)
                    HStack(spacing: 8) {
                        ActionButton(title: session.isPlaying ? "重新开始" : "沿路径开始",
                                     enabled: nodes.count >= 2) { start() }
                        ActionButton(title: session.isPlaying ? "暂停" : "继续",
                                     color: .orange, enabled: session.isPlaying) { togglePause() }
                        ActionButton(title: "停止", color: .gray, enabled: session.isPlaying) { stop() }
                    }
                    LabeledContent("状态", value: session.statusMessage)
                    LabeledContent("进度", value: String(format: "%.0f%%", session.progress * 100))
                    LabeledContent("段", value: session.segmentText.isEmpty ? "—" : session.segmentText)
                    LabeledContent("当前速度", value: String(format: "%.2f m/s", session.speedMps))
                }

                Section("已保存的路径") {
                    if routes.routes.isEmpty {
                        Text("还没有保存的路径").font(.caption).foregroundStyle(.secondary)
                    } else {
                        Picker("选择路径", selection: $selectedRouteId) {
                            Text("（不选择）").tag("")
                            ForEach(routes.routes) { r in
                                Text("\(r.name)（\(r.nodes.count) 点）").tag(r.id)
                            }
                        }
                        HStack {
                            Button("保存当前") { save() }
                            Button("载入所选") { load() }.disabled(selectedRouteId.isEmpty)
                            Button("删除所选", role: .destructive) { deleteSelected() }
                                .disabled(selectedRouteId.isEmpty)
                        }
                    }
                }

                if !message.isEmpty {
                    Section { Text(message).font(.caption).foregroundStyle(.secondary) }
                }
            }
            .navigationTitle("预设路径")
            .sheet(isPresented: $showMapPicker) {
                MapPickView(initialNodes: nodes, here: location.latest) { picked in
                    // 保留同序号节点的速度
                    var merged: [RouteNode] = []
                    for (i, n) in picked.enumerated() {
                        var node = n
                        node.speedMps = i < nodes.count ? nodes[i].speedMps : 0
                        merged.append(node)
                    }
                    nodes = merged
                    editingSpeeds = nodes.map { $0.speedMps > 0 ? String(format: "%.2f", $0.speedMps) : "" }
                    message = "从地图回来：\(nodes.count) 个节点"
                }
            }
            .onAppear {
                location.refresh()
                if nodes.isEmpty, let first = routes.routes.first {
                    selectedRouteId = first.id
                }
            }
        }
    }

    // MARK: - 派生数据

    private var previewTrack: Track? {
        guard nodes.count >= 2 else { return nil }
        var t = Track(name: name, points: nodes.enumerated().map { i, n in
            TrackPoint(t: i * 1000, lat: n.lat, lng: n.lng)
        })
        t.intervalMs = 1000
        return t
    }

    private func totalMeters() -> Double {
        guard nodes.count > 1 else { return 0 }
        var sum = 0.0
        for i in 1..<nodes.count {
            sum += GeoMath.distance(nodes[i - 1].lat, nodes[i - 1].lng, nodes[i].lat, nodes[i].lng)
        }
        return sum
    }

    private func bindingForSpeed(_ idx: Int) -> Binding<String> {
        Binding(
            get: { idx < editingSpeeds.count ? editingSpeeds[idx] : "" },
            set: { newValue in
                while editingSpeeds.count <= idx { editingSpeeds.append("") }
                editingSpeeds[idx] = newValue
                if idx < nodes.count {
                    nodes[idx].speedMps = parseDouble(newValue, fallback: 0, min: 0, max: 25)
                }
            }
        )
    }

    // MARK: - 动作

    private func start() {
        let route = buildRoute()
        engine.start(route: route, loop: loop, radius: 0, bias: 0, bearing: nil)
        client.playRoute(route, loop: loop, radius: 0, bias: 0, bearing: nil)
    }

    private func buildRoute() -> PresetRoute {
        var r = PresetRoute(name: name, nodes: nodes)
        r.globalSpeed = parseDouble(globalSpeed, fallback: 1.4, min: 0.2, max: 25)
        r.offsetPercent = parseDouble(offsetPercent, fallback: 20, min: 0, max: 90)
        r.loop = loop
        return r
    }

    private func togglePause() {
        if session.isPaused { engine.resume(); client.resume() } else { engine.pause(); client.pause() }
    }

    private func stop() {
        engine.stop()
        client.stop()
    }

    private func save() {
        var r = buildRoute()
        let existing = routes.routes.first { $0.id == selectedRouteId }
        if let existing { r.id = existing.id }
        routes.save(r)
        selectedRouteId = r.id
        message = "已保存：\(r.name)（\(r.nodes.count) 点）"
    }

    private func load() {
        guard let r = routes.load(selectedRouteId) else { return }
        name = r.name
        nodes = r.nodes
        editingSpeeds = nodes.map { $0.speedMps > 0 ? String(format: "%.2f", $0.speedMps) : "" }
        globalSpeed = String(format: "%.2f", r.globalSpeed)
        offsetPercent = String(format: "%.0f", r.offsetPercent)
        loop = r.loop
        message = "已载入：\(r.name)"
    }

    private func deleteSelected() {
        routes.delete(selectedRouteId)
        selectedRouteId = ""
        message = "已删除"
    }
}