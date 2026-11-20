//
//  RecordView.swift / LibraryView.swift
//

import SwiftUI

// MARK: - 录制页

struct RecordView: View {
    @ObservedObject var tracks: TrackStore
    @ObservedObject var client: CompanionClient
    @ObservedObject var location: LocationProvider
    @EnvironmentObject var session: InjectionSession

    @State private var name = ""
    @State private var interval = "500"
    @State private var minMove = "1.0"
    @State private var groupIndex = 0
    @State private var showNewGroup = false
    @State private var newGroupName = ""

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    HStack {
                        Circle()
                            .fill(session.isRecording ? Color.red : Color.gray.opacity(0.4))
                            .frame(width: 10, height: 10)
                        Text(session.isRecording ? "录制中：\(session.recordedPoints) 个点" : "未在录制")
                            .font(.subheadline)
                        Spacer()
                        if session.isRecording {
                            Text(session.statusMessage).font(.caption).foregroundStyle(.secondary)
                        }
                    }
                }

                Section("轨迹信息") {
                    TextField("名称（留空自动生成）", text: $name)
                    Picker("分组", selection: $groupIndex) {
                        ForEach(Array(tracks.groups.enumerated()), id: \.offset) { idx, g in
                            Text(g.name).tag(idx)
                        }
                    }
                    Button("新建分组") {
                        newGroupName = ""
                        showNewGroup = true
                    }
                }

                Section("采样参数") {
                    FieldRow(title: "采样间隔（毫秒）", value: $interval, keyboard: .numberPad, placeholder: "500")
                    FieldRow(title: "最小位移（米）", value: $minMove, placeholder: "1.0")
                    HintText(text: "位移超过「最小位移」就落一个点；原地不动时每 5 秒兜底落一个点。上限 20 万个点。")
                }

                Section("注入状态") {
                    LabeledContent("伴侣连接", value: client.state.text)
                    if session.hasPosition {
                        LabeledContent("当前注入坐标",
                                       value: String(format: "%.6f, %.6f", session.position.lat, session.position.lng))
                    }
                    LabeledContent("真实定位", value: location.message)
                    Button("取一次真实定位") { location.refresh() }
                }

                Section {
                    ActionButton(title: session.isRecording ? "停止录制并保存" : "开始录制",
                                 color: session.isRecording ? .red : .blue) {
                        toggle()
                    }
                    HintText(text: "录制的是「注入出去的坐标流」——也就是加了抖动后真正写进设备的点；这样录下来的轨迹才能原样重放。")
                }

                if !tracks.metas.isEmpty {
                    Section("最近轨迹") {
                        ForEach(tracks.metas.prefix(5)) { m in
                            VStack(alignment: .leading, spacing: 2) {
                                Text(m.name).font(.subheadline)
                                Text("\(tracks.groupName(m.groupId)) · \(m.subLabel)")
                                    .font(.caption2).foregroundStyle(.secondary)
                            }
                        }
                    }
                }
            }
            .navigationTitle("录制轨迹")
            .alert("新建分组", isPresented: $showNewGroup) {
                TextField("分组名", text: $newGroupName)
                Button("取消", role: .cancel) {}
                Button("创建") {
                    let g = tracks.createGroup(newGroupName)
                    groupIndex = tracks.groups.firstIndex { $0.id == g.id } ?? 0
                }
            }
        }
    }

    private func toggle() {
        if session.isRecording {
            let track = session.recorder.stop()
            session.isRecording = false
            if let track {
                let gid = tracks.groups.indices.contains(groupIndex) ? tracks.groups[groupIndex].id : TrackStore.defaultGroupId
                tracks.saveTrack(track, groupId: gid)
                session.status("已保存：\(track.name)（\(track.points.count) 点）")
                name = ""
            } else {
                session.status("点数不足 2 个，未保存")
            }
        } else {
            guard session.hasPosition || location.latest != nil else {
                session.status("还没有坐标：先连接伴侣程序，或点「取一次真实定位」")
                return
            }
            let gid = tracks.groups.indices.contains(groupIndex) ? tracks.groups[groupIndex].id : TrackStore.defaultGroupId
            session.recorder.configure(intervalMs: Int(parseDouble(interval, fallback: 500, min: 100, max: 5000)),
                                       minMoveMeters: parseDouble(minMove, fallback: 1.0, min: 0, max: 100))
            session.recorder.start(name: name, groupId: gid,
                                   nowMs: Int(Date().timeIntervalSince1970 * 1000))
            session.recordedPoints = 0
            session.isRecording = true
            if !session.hasPosition, let l = location.latest {
                session.inject(base: Coordinate(lat: l.lat, lng: l.lng))
            }
            session.status("录制开始")
        }
    }
}

// MARK: - 轨迹库

struct LibraryView: View {
    @ObservedObject var tracks: TrackStore
    @State private var filterGroup = ""
    @State private var renaming: TrackStore.TrackMeta?
    @State private var renameText = ""
    @State private var moving: TrackStore.TrackMeta?
    @State private var exporting: TrackStore.TrackMeta?

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 8) {
                        chip("全部（\(tracks.metas.count)）", active: filterGroup.isEmpty) { filterGroup = "" }
                        ForEach(tracks.groups) { g in
                            chip("\(g.name)（\(tracks.count(inGroup: g.id))）", active: filterGroup == g.id) {
                                filterGroup = g.id
                            }
                        }
                    }
                    .padding(.horizontal, 12)
                    .padding(.vertical, 8)
                }
                List {
                    ForEach(tracks.tracks(inGroup: filterGroup)) { m in
                        VStack(alignment: .leading, spacing: 3) {
                            Text(m.name).font(.subheadline)
                            Text("\(tracks.groupName(m.groupId)) · \(m.subLabel)")
                                .font(.caption2).foregroundStyle(.secondary)
                        }
                        .contentShape(Rectangle())
                        .contextMenu {
                            Button("重命名") { renaming = m; renameText = m.name }
                            Button("移动到分组") { moving = m }
                            Button("导出 GPX") { exporting = m }
                            Button("删除", role: .destructive) {
                                tracks.deleteTrack(m.id, groupId: m.groupId)
                            }
                        }
                    }
                }
                .listStyle(.plain)
                .overlay {
                    if tracks.tracks(inGroup: filterGroup).isEmpty {
                        ContentUnavailableView("还没有轨迹", systemImage: "square.stack.3d.up.slash",
                                               description: Text("去「录制」页录一条，或用「预设路径」在地图上画一条。"))
                    }
                }
            }
            .navigationTitle("轨迹库")
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button { tracks.reloadIndex() } label: { Image(systemName: "arrow.clockwise") }
                }
            }
            .alert("重命名", isPresented: Binding(get: { renaming != nil }, set: { if !$0 { renaming = nil } })) {
                TextField("名称", text: $renameText)
                Button("取消", role: .cancel) { renaming = nil }
                Button("保存") {
                    if let m = renaming { tracks.renameTrack(m.id, groupId: m.groupId, to: renameText) }
                    renaming = nil
                }
            }
            .confirmationDialog("移动到分组", isPresented: Binding(get: { moving != nil }, set: { if !$0 { moving = nil } }),
                                presenting: moving) { m in
                ForEach(tracks.groups) { g in
                    if g.id != m.groupId {
                        Button(g.name) {
                            tracks.moveTrack(m.id, from: m.groupId, to: g.id)
                            moving = nil
                        }
                    }
                }
                Button("取消", role: .cancel) { moving = nil }
            }
            .sheet(item: $exporting) { m in
                ExportView(meta: m)
            }
        }
    }

    private func chip(_ text: String, active: Bool, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Text(text)
                .font(.system(size: 12.5, weight: active ? .semibold : .regular))
                .padding(.horizontal, 12)
                .padding(.vertical, 6)
                .background(active ? Color.blue : Color.gray.opacity(0.15))
                .foregroundStyle(active ? .white : .primary)
                .clipShape(Capsule())
        }
    }
}

// MARK: - 导出

struct ExportView: View {
    let meta: TrackStore.TrackMeta
    @Environment(\.dismiss) private var dismiss
    @State private var gpx = ""

    var body: some View {
        NavigationStack {
            VStack(alignment: .leading, spacing: 12) {
                if let track = TrackStore.shared.loadTrack(meta.id, groupId: meta.groupId) {
                    Text(track.summary).font(.subheadline)
                    ShareLink(item: gpx, preview: SharePreview("\(track.name).gpx")) {
                        Label("分享 GPX 文件", systemImage: "square.and.arrow.up")
                    }
                    ShareLink(item: jsonText(track), preview: SharePreview("\(track.name).json")) {
                        Label("分享 JSON（给伴侣程序 play）", systemImage: "doc.text")
                    }
                    ScrollView {
                        Text(gpx).font(.system(size: 10, design: .monospaced))
                    }
                }
                Spacer()
            }
            .padding()
            .navigationTitle("导出 \(meta.name)")
            .onAppear {
                if let track = TrackStore.shared.loadTrack(meta.id, groupId: meta.groupId) {
                    gpx = track.toGPX()
                }
            }
            .toolbar { ToolbarItem(placement: .topBarTrailing) { Button("完成") { dismiss() } } }
        }
    }

    private func jsonText(_ track: Track) -> String {
        guard let data = try? JSONEncoder().encode(track) else { return "{}" }
        return String(data: data, encoding: .utf8) ?? "{}"
    }
}