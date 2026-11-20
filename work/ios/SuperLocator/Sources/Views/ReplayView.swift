//
//  ReplayView.swift / TrackPreview.swift
//  轨迹重放页：选轨迹 → 设速度 → 设随机值（半径 / 权重偏于 / 方位角）→ 播放，
//  顶部 Canvas 预览轨迹折线、起终点、基准点与注入点。
//

import SwiftUI

// MARK: - 预览画布

struct TrackPreviewView: View {
    var track: Track?
    var base: Coordinate?
    var injected: Coordinate?
    var progress: Double = 0
    var offsetMeters: Double = 0

    var body: some View {
        Canvas { ctx, size in
            let rect = CGRect(origin: .zero, size: size)
            ctx.fill(Path(rect), with: .color(Color(red: 0.063, green: 0.082, blue: 0.122)))

            // 网格
            var grid = Path()
            for i in 1...5 {
                let x = size.width * CGFloat(i) / 6
                let y = size.height * CGFloat(i) / 6
                grid.move(to: CGPoint(x: x, y: 0)); grid.addLine(to: CGPoint(x: x, y: size.height))
                grid.move(to: CGPoint(x: 0, y: y)); grid.addLine(to: CGPoint(x: size.width, y: y))
            }
            ctx.stroke(grid, with: .color(Color(red: 0.35, green: 0.39, blue: 0.47).opacity(0.25)), lineWidth: 0.5)

            guard let track, track.points.count > 1 else {
                var text = Text("还没有轨迹")
                text.font = .system(size: 12)
                ctx.draw(text, at: CGPoint(x: size.width / 2, y: size.height / 2))
                return
            }

            let project = Projector(track: track, size: size)
            var path = Path()
            for (i, p) in track.points.enumerated() {
                let pt = project.point(p.lat, p.lng)
                if i == 0 { path.move(to: pt) } else { path.addLine(to: pt) }
            }
            ctx.stroke(path, with: .color(Color(red: 0.306, green: 0.631, blue: 1).opacity(0.25)), lineWidth: 7)
            ctx.stroke(path, with: .color(Color(red: 0.306, green: 0.631, blue: 1)), lineWidth: 2.2)

            if let first = track.points.first {
                dot(ctx, project.point(first.lat, first.lng), r: 4.5, color: Color(red: 0.18, green: 0.83, blue: 0.48))
            }
            if let last = track.points.last {
                dot(ctx, project.point(last.lat, last.lng), r: 5, color: Color(red: 1, green: 0.69, blue: 0.13))
            }
            if let base, let injected {
                let pb = project.point(base.lat, base.lng)
                let pj = project.point(injected.lat, injected.lng)
                var link = Path(); link.move(to: pb); link.addLine(to: pj)
                ctx.stroke(link, with: .color(Color(red: 0.6, green: 0.64, blue: 0.7).opacity(0.7)), lineWidth: 1)
                dot(ctx, pb, r: 3.5, color: Color(red: 0.6, green: 0.64, blue: 0.7))
                dot(ctx, pj, r: 9, color: Color(red: 1, green: 0.23, blue: 0.34).opacity(0.35))
                dot(ctx, pj, r: 4.5, color: Color(red: 1, green: 0.23, blue: 0.34))
            }

            var left = Text("\(track.points.count) 点 · \(Int(track.distanceM.rounded())) m · \(Track.formatDuration(track.durationMs))")
            left.font = .system(size: 9)
            left.foregroundColor = Color(red: 0.66, green: 0.7, blue: 0.78)
            ctx.draw(left, at: CGPoint(x: 8, y: size.height - 10), anchor: .leading)

            var right = Text(String(format: "重放 %.0f%% · 偏移 %.1f m", progress * 100, offsetMeters))
            right.font = .system(size: 9)
            right.foregroundColor = Color(red: 0.66, green: 0.7, blue: 0.78)
            ctx.draw(right, at: CGPoint(x: size.width - 8, y: size.height - 10), anchor: .trailing)
        }
        .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 12).stroke(Color.white.opacity(0.08)))
    }

    private func dot(_ ctx: GraphicsContext, _ p: CGPoint, r: CGFloat, color: Color) {
        ctx.fill(Path(ellipseIn: CGRect(x: p.x - r, y: p.y - r, width: r * 2, height: r * 2)), with: .color(color))
    }

    /// 以首点为原点、正北朝上的等比例投影
    struct Projector {
        let cx: Double
        let cy: Double
        let scale: Double
        let ox: CGFloat
        let oy: CGFloat
        let kx: Double
        let ky: Double

        init(track: Track, size: CGSize) {
            let base = track.points[0]
            cx = base.lat
            cy = base.lng
            kx = 111_132.92 * max(0.02, cos(base.lat * .pi / 180))
            ky = 111_132.92
            var minX = Double.infinity, maxX = -Double.infinity
            var minY = Double.infinity, maxY = -Double.infinity
            for p in track.points {
                let x = (p.lng - cy) * kx
                let y = (p.lat - cx) * ky
                minX = min(minX, x); maxX = max(maxX, x)
                minY = min(minY, y); maxY = max(maxY, y)
            }
            let spanX = max(24, maxX - minX)
            let spanY = max(24, maxY - minY)
            let availW = Double(size.width) - 24
            let availH = Double(size.height) - 34
            scale = max(0.02, min(availW / spanX, availH / spanY))
            ox = size.width / 2 - CGFloat((minX + maxX) / 2 * scale)
            oy = size.height / 2 + CGFloat((minY + maxY) / 2 * scale) - 6
        }

        func point(_ lat: Double, _ lng: Double) -> CGPoint {
            let x = (lng - cy) * kx * scale
            let y = (lat - cx) * ky * scale
            return CGPoint(x: ox + CGFloat(x), y: oy - CGFloat(y))
        }
    }
}

// MARK: - 重放页

struct ReplayView: View {
    @ObservedObject var tracks: TrackStore
    @ObservedObject var client: CompanionClient
    @EnvironmentObject var session: InjectionSession

    @StateObject private var engine = ReplayEngine()
    @State private var trackIndex = 0
    @State private var speed = "1.0"
    @State private var loop = false
    @State private var radius = "20"
    @State private var weight: Double = 55
    @State private var bearing = ""
    @State private var previewTrack: Track?

    private var list: [TrackStore.TrackMeta] { tracks.metas }
    private var selected: TrackStore.TrackMeta? {
        list.indices.contains(trackIndex) ? list[trackIndex] : nil
    }

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    TrackPreviewView(track: previewTrack,
                                     base: session.hasPosition ? session.position : nil,
                                     injected: session.hasPosition ? session.position : nil,
                                     progress: session.progress,
                                     offsetMeters: currentOffset)
                        .frame(height: 200)
                        .listRowInsets(EdgeInsets(top: 6, leading: 6, bottom: 6, trailing: 6))
                    HintText(text: "蓝线是录制的轨迹（正北朝上），绿点起点、橙点终点；红点是加了「权重偏于」抖动后真正注入的坐标。")
                }

                Section("选择轨迹") {
                    if list.isEmpty {
                        Text("还没有轨迹，先去「录制」页录一条").font(.caption).foregroundStyle(.secondary)
                    } else {
                        Picker("轨迹（分组 / 名称）", selection: $trackIndex) {
                            ForEach(Array(list.enumerated()), id: \.offset) { idx, m in
                                Text("\(tracks.groupName(m.groupId)) / \(m.name)（\(m.pointCount) 点）").tag(idx)
                            }
                        }
                        .onChange(of: trackIndex) { _, _ in loadPreview() }
                        Button("刷新列表") {
                            tracks.reloadIndex()
                            trackIndex = 0
                            loadPreview()
                        }
                    }
                    FieldRow(title: "播放速度倍率（0.1~20）", value: $speed, placeholder: "1.0")
                    Toggle("循环播放（到终点后回到起点继续）", isOn: $loop)
                }

                Section("随机值 / 权重偏于") {
                    HintText(text: "半径：注入点离轨迹基准点的最大距离。权重：越大越贴着指定方位角跑，越小越像随机游走。方位角留空则每次随机。")
                    FieldRow(title: "抖动半径（米，0~500）", value: $radius, placeholder: "20")
                    HStack {
                        Text("权重偏于").font(.subheadline)
                        Slider(value: $weight, in: 0...100, step: 1)
                        Text("\(Int(weight))%").font(.caption).monospacedDigit().frame(width: 40)
                    }
                    Text(weightLabel).font(.caption2).foregroundStyle(.blue)
                    FieldRow(title: "偏向方位角（度，留空=随机）", value: $bearing, placeholder: "例如 90")
                }

                Section("控制") {
                    HStack(spacing: 8) {
                        ActionButton(title: session.isPlaying ? "重新开始" : "开始重放",
                                     enabled: selected != nil) { start() }
                        ActionButton(title: session.isPlaying ? "暂停" : "继续",
                                     color: .orange, enabled: session.isPlaying) { togglePause() }
                        ActionButton(title: "停止", color: .gray, enabled: session.isPlaying) { stop() }
                    }
                    LabeledContent("状态", value: session.statusMessage)
                    LabeledContent("进度", value: String(format: "%.0f%%", session.progress * 100))
                    LabeledContent("当前速度", value: String(format: "%.2f m/s", session.speedMps))
                    LabeledContent("抖动", value: session.jitterText)
                    LabeledContent("伴侣连接", value: client.state.text)
                }

                Section("工作方式") {
                    HintText(text: "1) 电脑运行 superlocator.py serve；2) 本页点「开始重放」；3) App 每 100 ms 算出坐标 + 抖动，通过 TCP 交给伴侣程序，伴侣程序用开发者服务写进设备。原 App 的手动移动（地图选点 + 起飞 + 悬浮摇杆）在 Android 版里保留，iOS 侧靠伴侣程序的 set 命令配合。")
                }
            }
            .navigationTitle("轨迹重放")
            .onAppear { loadPreview() }
        }
    }

    private var currentOffset: Double {
        guard let base = previewTrack, session.hasPosition else { return 0 }
        let p = GeoMath.interpolate(base, atMs: session.progress * Double(base.durationMs))
        return GeoMath.distance(p.0, p.1, session.position.lat, session.position.lng)
    }

    private var weightLabel: String {
        if weight == 0 { return "· 纯随机，不偏向" }
        if weight >= 90 { return "· 强偏向指定方向" }
        return "· 偏向指定方向"
    }

    private func loadPreview() {
        guard let m = selected else { previewTrack = nil; return }
        previewTrack = tracks.loadTrack(m.id, groupId: m.groupId)
    }

    private func start() {
        guard let m = selected, let track = tracks.loadTrack(m.id, groupId: m.groupId) else { return }
        previewTrack = track
        let r = parseDouble(radius, fallback: 20, min: 0, max: 500)
        let b = bearing.trimmingCharacters(in: .whitespaces).isEmpty ? nil : Double(bearing)
        engine.start(track: track,
                     speed: parseDouble(speed, fallback: 1.0, min: 0.1, max: 20),
                     loop: loop, radius: r, bias: weight / 100, bearing: b)
        client.playTrack(track, speed: parseDouble(speed, fallback: 1.0, min: 0.1, max: 20),
                         loop: loop, radius: r, bias: weight / 100, bearing: b)
    }

    private func togglePause() {
        if session.isPaused { engine.resume(); client.resume() } else { engine.pause(); client.pause() }
    }

    private func stop() {
        engine.stop()
        client.stop()
    }
}