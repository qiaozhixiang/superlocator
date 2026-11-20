//
//  Stores.swift
//  本地存储：Documents/VTracks/groups.json + index.json + <groupId>/<trackId>.json
//  与 Android 版 TrackStore 的目录结构一一对应，方便两端互相拷贝。
//

import Foundation
import Combine

// MARK: - 通用 JSON 存储

enum JsonStorage {
    static var root: URL {
        let base = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
        return base.appendingPathComponent("VTracks", isDirectory: true)
    }

    static func ensureDir(_ url: URL) {
        try? FileManager.default.createDirectory(at: url, withIntermediateDirectories: true)
    }

    static func read<T: Decodable>(_ type: T.Type, from url: URL) -> T? {
        guard let data = try? Data(contentsOf: url) else { return nil }
        return try? JSONDecoder().decode(type, from: data)
    }

    static func write<T: Encodable>(_ value: T, to url: URL) {
        ensureDir(url.deletingLastPathComponent())
        guard let data = try? JSONEncoder().encode(value) else { return }
        let tmp = url.appendingPathExtension("tmp")
        do {
            try data.write(to: tmp, options: .atomic)
            _ = try FileManager.default.replaceItemAt(url, withItemAt: tmp)
        } catch {
            try? data.write(to: url, options: .atomic)
        }
    }

    static func sanitize(_ raw: String) -> String {
        let allowed = CharacterSet(charactersIn: "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-.")
        return String(raw.unicodeScalars.map { allowed.contains($0) ? Character($0) : "_" })
    }
}

// MARK: - 轨迹库

final class TrackStore: ObservableObject {
    static let defaultGroupId = "default"
    static let defaultGroupName = "默认分组"
    static let shared = TrackStore()

    @Published private(set) var groups: [TrackGroup] = []
    @Published private(set) var metas: [TrackMeta] = []

    struct TrackMeta: Codable, Identifiable, Hashable {
        var id: String
        var name: String
        var groupId: String
        var createdAt: Int64
        var durationMs: Int
        var pointCount: Int
        var distanceM: Double

        var label: String { name }
        var subLabel: String {
            "\(Track.formatDuration(durationMs)) · \(Int(distanceM.rounded())) m · \(pointCount) 点"
        }
    }

    private var root: URL { JsonStorage.root }

    init() {
        JsonStorage.ensureDir(root)
        loadGroups()
        reloadIndex()
    }

    // 分组 -------------------------------------------------------------
    func loadGroups() {
        let url = root.appendingPathComponent("groups.json")
        if let list = JsonStorage.read([TrackGroup].self, from: url), !list.isEmpty {
            groups = list
        } else {
            groups = [TrackGroup(id: Self.defaultGroupId, name: Self.defaultGroupName)]
            JsonStorage.write(groups, to: url)
        }
        if !groups.contains(where: { $0.id == Self.defaultGroupId }) {
            groups.insert(TrackGroup(id: Self.defaultGroupId, name: Self.defaultGroupName), at: 0)
        }
    }

    func createGroup(_ name: String) -> TrackGroup {
        let g = TrackGroup(id: "g" + UUID().uuidString.prefix(8), name: name.isEmpty ? "新分组" : name)
        groups.append(g)
        JsonStorage.write(groups, to: root.appendingPathComponent("groups.json"))
        return g
    }

    func renameGroup(_ id: String, to name: String) {
        guard let i = groups.firstIndex(where: { $0.id == id }) else { return }
        groups[i].name = name
        JsonStorage.write(groups, to: root.appendingPathComponent("groups.json"))
    }

    func deleteGroup(_ id: String) {
        guard id != Self.defaultGroupId else { return }
        // 组内轨迹移到默认组
        for meta in metas where meta.groupId == id {
            var t = loadTrack(meta.id, groupId: id)
            t?.groupId = Self.defaultGroupId
            if let t { saveTrack(t, groupId: Self.defaultGroupId) }
            deleteTrack(meta.id, groupId: id)
        }
        groups.removeAll { $0.id == id }
        JsonStorage.write(groups, to: root.appendingPathComponent("groups.json"))
        reloadIndex()
    }

    func groupName(_ id: String) -> String {
        groups.first { $0.id == id }?.name ?? Self.defaultGroupName
    }

    func count(inGroup id: String) -> Int {
        metas.filter { $0.groupId == id }.count
    }

    // 轨迹 -------------------------------------------------------------
    private func groupDir(_ groupId: String) -> URL {
        root.appendingPathComponent(JsonStorage.sanitize(groupId), isDirectory: true)
    }

    private func trackURL(_ id: String, groupId: String) -> URL {
        groupDir(groupId).appendingPathComponent(JsonStorage.sanitize(id) + ".json")
    }

    func saveTrack(_ track: Track, groupId: String) {
        var t = track
        t.groupId = groupId
        JsonStorage.write(t, to: trackURL(t.id, groupId: groupId))
        upsertIndex(t)
    }

    func loadTrack(_ id: String, groupId: String) -> Track? {
        JsonStorage.read(Track.self, from: trackURL(id, groupId: groupId))
    }

    func deleteTrack(_ id: String, groupId: String) {
        try? FileManager.default.removeItem(at: trackURL(id, groupId: groupId))
        metas.removeAll { $0.id == id }
        JsonStorage.write(metas, to: root.appendingPathComponent("index.json"))
    }

    func renameTrack(_ id: String, groupId: String, to name: String) {
        guard var t = loadTrack(id, groupId: groupId) else { return }
        t.name = name
        saveTrack(t, groupId: groupId)
    }

    func moveTrack(_ id: String, from: String, to target: String) {
        guard var t = loadTrack(id, groupId: from) else { return }
        t.groupId = target
        saveTrack(t, groupId: target)
        deleteTrack(id, groupId: from)
    }

    // 索引 -------------------------------------------------------------
    func reloadIndex() {
        var list: [TrackMeta] = []
        for g in groups {
            let dir = groupDir(g.id)
            guard let files = try? FileManager.default.contentsOfDirectory(at: dir, includingPropertiesForKeys: nil) else { continue }
            for f in files where f.pathExtension == "json" {
                if let t = JsonStorage.read(Track.self, from: f) {
                    list.append(TrackMeta(id: t.id, name: t.name, groupId: g.id, createdAt: t.createdAt,
                                          durationMs: t.durationMs, pointCount: t.points.count,
                                          distanceM: t.distanceM))
                }
            }
        }
        metas = list.sorted { $0.createdAt > $1.createdAt }
        JsonStorage.write(metas, to: root.appendingPathComponent("index.json"))
    }

    private func upsertIndex(_ t: Track) {
        metas.removeAll { $0.id == t.id }
        metas.insert(TrackMeta(id: t.id, name: t.name, groupId: t.groupId, createdAt: t.createdAt,
                               durationMs: t.durationMs, pointCount: t.points.count, distanceM: t.distanceM), at: 0)
        JsonStorage.write(metas, to: root.appendingPathComponent("index.json"))
    }

    func meta(_ id: String) -> TrackMeta? { metas.first { $0.id == id } }

    func tracks(inGroup id: String) -> [TrackMeta] {
        id.isEmpty ? metas : metas.filter { $0.groupId == id }
    }
}

// MARK: - 预设路径库

final class RouteStore: ObservableObject {
    static let shared = RouteStore()
    @Published private(set) var routes: [PresetRoute] = []

    private var root: URL { JsonStorage.root.appendingPathComponent("Routes", isDirectory: true) }

    init() { reload() }

    func reload() {
        JsonStorage.ensureDir(root)
        var list: [PresetRoute] = []
        if let files = try? FileManager.default.contentsOfDirectory(at: root, includingPropertiesForKeys: nil) {
            for f in files where f.pathExtension == "json" {
                if let r = JsonStorage.read(PresetRoute.self, from: f) { list.append(r) }
            }
        }
        routes = list.sorted { $0.createdAt > $1.createdAt }
    }

    func save(_ route: PresetRoute) {
        JsonStorage.write(route, to: root.appendingPathComponent(JsonStorage.sanitize(route.id) + ".json"))
        reload()
    }

    func delete(_ id: String) {
        try? FileManager.default.removeItem(at: root.appendingPathComponent(JsonStorage.sanitize(id) + ".json"))
        reload()
    }

    func load(_ id: String) -> PresetRoute? {
        routes.first { $0.id == id }
    }
}