//
//  MapPickView.swift
//  地图选点：点地图落节点、搜索地名跳转、放大缩小、清空 / 撤销 / 恢复。
//  用 MapKit（苹果地图），坐标全部按 WGS-84 存储，与注入通道一致。
//

import SwiftUI
import MapKit

struct MapPickView: View {
    /// 传入：已有节点（WGS-84）；传出：RESULT 节点
    var initialNodes: [RouteNode] = []
    var here: Coordinate?
    var onDone: ([RouteNode]) -> Void

    @Environment(\.dismiss) private var dismiss
    @State private var nodes: [RouteNode] = []
    @State private var undoStack: [[RouteNode]] = []
    @State private var redoStack: [[RouteNode]] = []
    @State private var camera: MapCameraPosition = .region(
        MKCoordinateRegion(center: CLLocationCoordinate2D(latitude: 36.667662, longitude: 117.027707),
                           span: MKCoordinateSpan(latitudeDelta: 0.02, longitudeDelta: 0.02)))
    @State private var query = ""
    @State private var busy = false
    @State private var message = ""
    @State private var pickLocked = false
    @State private var results: [MKMapItem] = []
    @State private var showResults = false

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                searchBar
                toolBar
                ZStack(alignment: .top) {
                    map
                    if !message.isEmpty {
                        Text(message)
                            .font(.caption2)
                            .padding(.horizontal, 10).padding(.vertical, 5)
                            .background(.ultraThinMaterial)
                            .clipShape(Capsule())
                            .padding(.top, 8)
                    }
                }
                statusBar
            }
            .navigationTitle("地图选点")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) { Button("取消") { dismiss() } }
                ToolbarItem(placement: .topBarTrailing) {
                    Button("完成") { onDone(nodes); dismiss() }
                        .disabled(nodes.count < 2)
                }
            }
            .onAppear(perform: bootstrap)
            .sheet(isPresented: $showResults) { resultSheet }
        }
    }

    // MARK: - 地图

    private var map: some View {
        MapReader { proxy in
            Map(position: $camera) {
                ForEach(Array(nodes.enumerated()), id: \.offset) { idx, node in
                    Annotation("\(idx + 1)", coordinate: CLLocationCoordinate2D(latitude: node.lat, longitude: node.lng)) {
                        Text("\(idx + 1)")
                            .font(.caption2.bold())
                            .foregroundStyle(.white)
                            .frame(width: 26, height: 26)
                            .background(color(idx))
                            .clipShape(Circle())
                            .overlay(Circle().stroke(.white, lineWidth: 1.5))
                    }
                }
                if let here {
                    Annotation("当前定位", coordinate: CLLocationCoordinate2D(latitude: here.lat, longitude: here.lng)) {
                        Image(systemName: "location.fill")
                            .font(.caption)
                            .foregroundStyle(.white)
                            .padding(6)
                            .background(Color.blue)
                            .clipShape(Circle())
                    }
                }
            }
            .mapControls { MapCompass(); MapScaleView() }
            .onTapGesture { location in
                guard !pickLocked, let coord = proxy.convert(location, from: .local) else { return }
                add(coord)
            }
        }
    }

    private func color(_ idx: Int) -> Color {
        if idx == 0 { return .green }
        if idx == nodes.count - 1 { return .orange }
        return .blue
    }

    // MARK: - 搜索

    private var searchBar: some View {
        HStack(spacing: 8) {
            TextField("搜地点（如 山东科技大学）或 36.6676,117.0277", text: $query)
                .textFieldStyle(.roundedBorder)
                .submitLabel(.search)
                .onSubmit(runSearch)
            Button {
                runSearch()
            } label: {
                if busy { ProgressView() } else { Image(systemName: "magnifyingglass") }
            }
            .disabled(busy || query.trimmingCharacters(in: .whitespaces).isEmpty)
        }
        .padding(.horizontal, 12).padding(.vertical, 8)
    }

    private var toolBar: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 8) {
                smallButton("清空节点", "trash") { mutate { $0 = [] } }
                smallButton("撤销", "arrow.uturn.backward") { undo() }
                smallButton("恢复", "arrow.uturn.forward") { redo() }
                smallButton("放大", "plus.magnifyingglass") { zoom(0.5) }
                smallButton("缩小", "minus.magnifyingglass") { zoom(2.0) }
                smallButton(pickLocked ? "恢复拾取" : "暂停拾取", "hand.tap") { pickLocked.toggle() }
                smallButton("回当前定位", "location") { goHere() }
            }
            .padding(.horizontal, 12).padding(.bottom, 8)
        }
    }

    private func smallButton(_ title: String, _ icon: String, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Label(title, systemImage: icon)
                .font(.system(size: 12))
                .padding(.horizontal, 10).padding(.vertical, 6)
                .background(Color.gray.opacity(0.14))
                .clipShape(Capsule())
        }
    }

    private var statusBar: some View {
        HStack {
            Text(statusText).font(.caption2).foregroundStyle(.secondary)
            Spacer()
            Text(String(format: "z %.2f", camera.region?.span.latitudeDelta ?? 0))
                .font(.caption2).monospacedDigit().foregroundStyle(.secondary)
        }
        .padding(.horizontal, 12).padding(.vertical, 6)
        .background(.bar)
    }

    private var statusText: String {
        let head: String
        if let first = nodes.first {
            head = String(format: "共 %d 节点 · 首点 %.6f, %.6f · 总长 %.0f m",
                          nodes.count, first.lat, first.lng, totalMeters())
        } else {
            head = "共 0 节点 · 点地图落第一个节点"
        }
        return pickLocked ? head + " ·（已暂停拾取）" : head
    }

    private func totalMeters() -> Double {
        guard nodes.count > 1 else { return 0 }
        var sum = 0.0
        for i in 1..<nodes.count {
            sum += GeoMath.distance(nodes[i - 1].lat, nodes[i - 1].lng, nodes[i].lat, nodes[i].lng)
        }
        return sum
    }

    // MARK: - 操作

    private func bootstrap() {
        nodes = initialNodes
        if let here {
            camera = .region(MKCoordinateRegion(
                center: CLLocationCoordinate2D(latitude: here.lat, longitude: here.lng),
                span: MKCoordinateSpan(latitudeDelta: 0.01, longitudeDelta: 0.01)))
        } else if let first = initialNodes.first {
            camera = .region(MKCoordinateRegion(
                center: CLLocationCoordinate2D(latitude: first.lat, longitude: first.lng),
                span: MKCoordinateSpan(latitudeDelta: 0.01, longitudeDelta: 0.01)))
        }
    }

    /// 所有修改都走这里，自动压栈（撤销/恢复）
    private func mutate(_ change: (inout [RouteNode]) -> Void) {
        undoStack.append(nodes)
        if undoStack.count > 200 { undoStack.removeFirst() }
        redoStack.removeAll()
        change(&nodes)
    }

    private func add(_ coord: CLLocationCoordinate2D) {
        // 与已有节点太近就跳过，避免“点了没反应/叠在一起”
        for n in nodes {
            if GeoMath.distance(n.lat, n.lng, coord.latitude, coord.longitude) < 3 {
                message = "这个位置已经有节点了"
                return
            }
        }
        mutate { $0.append(RouteNode(lat: coord.latitude, lng: coord.longitude)) }
        message = "已添加第 \(nodes.count) 个节点"
    }

    private func undo() {
        guard let last = undoStack.popLast() else { return }
        redoStack.append(nodes)
        nodes = last
        message = "已撤销"
    }

    private func redo() {
        guard let next = redoStack.popLast() else { return }
        undoStack.append(nodes)
        nodes = next
        message = "已恢复"
    }

    private func zoom(_ factor: Double) {
        var region = camera.region ?? MKCoordinateRegion(
            center: CLLocationCoordinate2D(latitude: 36.667662, longitude: 117.027707),
            span: MKCoordinateSpan(latitudeDelta: 0.02, longitudeDelta: 0.02))
        region.span.latitudeDelta = min(60, max(0.0005, region.span.latitudeDelta * factor))
        region.span.longitudeDelta = min(60, max(0.0005, region.span.longitudeDelta * factor))
        camera = .region(region)
    }

    private func goHere() {
        guard let here else { message = "没有当前定位"; return }
        camera = .region(MKCoordinateRegion(
            center: CLLocationCoordinate2D(latitude: here.lat, longitude: here.lng),
            span: MKCoordinateSpan(latitudeDelta: 0.004, longitudeDelta: 0.004)))
        message = String(format: "当前定位 %.6f, %.6f", here.lat, here.lng)
    }

    private func jump(to lat: Double, _ lng: Double, label: String) {
        camera = .region(MKCoordinateRegion(
            center: CLLocationCoordinate2D(latitude: lat, longitude: lng),
            span: MKCoordinateSpan(latitudeDelta: 0.004, longitudeDelta: 0.004)))
        message = "已跳到 \(label)，点地图落点即可"
    }

    // MARK: - 搜索实现

    private func runSearch() {
        let raw = query.trimmingCharacters(in: .whitespaces)
        guard !raw.isEmpty else { return }
        if let pair = Self.parseLatLng(raw) {
            jump(to: pair.lat, pair.lng, label: String(format: "%.6f, %.6f", pair.lat, pair.lng))
            return
        }
        busy = true
        message = "搜索中…"
        let request = MKLocalSearch.Request()
        request.naturalLanguageQuery = raw
        request.region = MKCoordinateRegion(
            center: camera.region?.center ?? CLLocationCoordinate2D(latitude: 36.667662, longitude: 117.027707),
            span: MKCoordinateSpan(latitudeDelta: 2.0, longitudeDelta: 2.0))
        MKLocalSearch(request: request).start { response, error in
            busy = false
            if let error {
                message = "搜索失败：\(error.localizedDescription)"
                return
            }
            results = response?.mapItems.prefix(20).map { $0 } ?? []
            if results.isEmpty {
                message = "没有找到「\(raw)」"
            } else {
                message = "找到 \(results.count) 个结果"
                showResults = true
            }
        }
    }

    private var resultSheet: some View {
        NavigationStack {
            List {
                ForEach(Array(results.enumerated()), id: \.offset) { _, item in
                    Button {
                        let c = item.placemark.coordinate
                        showResults = false
                        jump(to: c.latitude, c.longitude, label: item.name ?? "结果")
                    } label: {
                        VStack(alignment: .leading, spacing: 3) {
                            Text(item.name ?? "未命名").font(.subheadline)
                            Text(item.placemark.title ?? "")
                                .font(.caption2).foregroundStyle(.secondary)
                        }
                    }
                }
            }
            .navigationTitle("搜索结果")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .topBarTrailing) { Button("关闭") { showResults = false } } }
        }
    }

    /// 支持「36.6676,117.0277」「36.6676 117.0277」，纬度>90 时自动交换
    static func parseLatLng(_ raw: String) -> Coordinate? {
        let cleaned = raw.replacingOccurrences(of: "，", with: ",")
            .replacingOccurrences(of: " ", with: ",")
        let parts = cleaned.split(whereSeparator: { $0 == "," || $0 == ";" }).filter { !$0.isEmpty }
        guard parts.count == 2,
              let a = Double(parts[0]), let b = Double(parts[1]) else { return nil }
        let lat = abs(a) <= 90 ? a : b
        let lng = abs(a) <= 90 ? b : a
        guard abs(lat) <= 90, abs(lng) <= 180 else { return nil }
        return Coordinate(lat: lat, lng: lng)
    }
}