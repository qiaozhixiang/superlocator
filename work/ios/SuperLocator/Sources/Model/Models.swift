//
//  Models.swift
//  SuperLocator
//
//  与伴侣程序（superlocator.py）完全一致的 JSON 模型：
//  轨迹点编码为 [t, lat, lng] 三元数组，节点编码为 [lat, lng, speedMps]，
//  这样 iOS 导出的文件可以直接 `python superlocator.py play --file x.json` 播放。
//

import Foundation
import Combine

// MARK: - 轨迹点

struct TrackPoint: Codable, Hashable {
    var t: Int          // 相对起点的毫秒
    var lat: Double
    var lng: Double

    init(t: Int, lat: Double, lng: Double) {
        self.t = t
        self.lat = lat
        self.lng = lng
    }

    init(from decoder: Decoder) throws {
        var c = try decoder.unkeyedContainer()
        t = try c.decode(Int.self)
        lat = try c.decode(Double.self)
        lng = try c.decode(Double.self)
    }

    func encode(to encoder: Encoder) throws {
        var c = encoder.unkeyedContainer()
        try c.encode(t)
        try c.encode((lat * 1e6).rounded() / 1e6)
        try c.encode((lng * 1e6).rounded() / 1e6)
    }
}

// MARK: - 轨迹

struct Track: Codable, Identifiable, Hashable {
    var id: String = UUID().uuidString
    var name: String = "轨迹"
    var groupId: String = TrackStore.defaultGroupId
    var createdAt: Int64 = Int64(Date().timeIntervalSince1970 * 1000)
    var intervalMs: Int = 500
    var points: [TrackPoint] = []

    var durationMs: Int {
        guard let f = points.first, let l = points.last, l.t > f.t else { return 0 }
        return l.t - f.t
    }

    var distanceM: Double {
        guard points.count > 1 else { return 0 }
        var total = 0.0
        for i in 1..<points.count {
            total += GeoMath.distance(points[i - 1].lat, points[i - 1].lng,
                                      points[i].lat, points[i].lng)
        }
        return total
    }

    var summary: String {
        "\(points.count) 点 · \(Int(distanceM.rounded())) m · \(Track.formatDuration(durationMs))"
    }

    /// 首点归零、时间严格单调（与 Android 版 normalizeTimeline 等价）
    mutating func normalizeTimeline() {
        guard !points.isEmpty else { return }
        let base = points[0].t
        var last = -1
        for i in points.indices {
            var t = points[i].t - base
            if t <= last { t = last + 1 }
            last = t
            points[i].t = t
        }
    }

    static func formatDuration(_ ms: Int) -> String {
        let total = max(0, ms) / 1000
        let m = total / 60, s = total % 60
        if m >= 60 { return String(format: "%d:%02d:%02d", m / 60, m % 60, s) }
        return String(format: "%d:%02d", m, s)
    }

    func toGPX() -> String {
        var body = ""
        for p in points {
            let iso = ISO8601DateFormatter().string(from: Date(timeIntervalSince1970: 1_700_000_000 + Double(p.t) / 1000))
            body += "      <trkpt lat=\"\(String(format: "%.6f", p.lat))\" lon=\"\(String(format: "%.6f", p.lng))\"><time>\(iso)</time></trkpt>\n"
        }
        return """
        <?xml version="1.0" encoding="UTF-8"?>
        <gpx version="1.1" creator="SuperLocator" xmlns="http://www.topografix.com/GPX/1/1">
          <trk><name>\(name)</name><trkseg>
        \(body)  </trkseg></trk>
        </gpx>
        """
    }
}

// MARK: - 分组

struct TrackGroup: Codable, Identifiable, Hashable {
    var id: String
    var name: String
    var createdAt: Int64 = Int64(Date().timeIntervalSince1970 * 1000)
}

// MARK: - 预设路径

struct RouteNode: Codable, Hashable, Identifiable {
    var id = UUID()
    var lat: Double
    var lng: Double
    var speedMps: Double = 0        // 0 = 跟随全局

    enum CodingKeys: String, CodingKey { case lat, lng, speedMps }

    init(lat: Double, lng: Double, speedMps: Double = 0) {
        self.lat = lat
        self.lng = lng
        self.speedMps = speedMps
    }

    init(from decoder: Decoder) throws {
        if let c = try? decoder.unkeyedContainer() {
            var cc = c
            lat = try cc.decode(Double.self)
            lng = try cc.decode(Double.self)
            speedMps = (try? cc.decode(Double.self)) ?? 0
        } else {
            let c = try decoder.container(keyedBy: CodingKeys.self)
            lat = try c.decode(Double.self, forKey: .lat)
            lng = try c.decode(Double.self, forKey: .lng)
            speedMps = (try? c.decode(Double.self, forKey: .speedMps)) ?? 0
        }
    }

    func encode(to encoder: Encoder) throws {
        var c = encoder.unkeyedContainer()
        try c.encode((lat * 1e6).rounded() / 1e6)
        try c.encode((lng * 1e6).rounded() / 1e6)
        try c.encode((speedMps * 1000).rounded() / 1000)
    }

    func describe(_ index: Int) -> String {
        let speed = speedMps > 0 ? String(format: "%.2f m/s", speedMps) : "跟随全局"
        return String(format: "%d. %.6f, %.6f · %@", index + 1, lat, lng, speed)
    }
}

struct PresetRoute: Codable, Identifiable, Hashable {
    var id: String = UUID().uuidString
    var name: String = "预设路径"
    var createdAt: Int64 = Int64(Date().timeIntervalSince1970 * 1000)
    var globalSpeed: Double = 1.4
    var offsetPercent: Double = 20
    var loop: Bool = false
    var nodes: [RouteNode] = []

    var segmentMeters: [Double] {
        guard nodes.count > 1 else { return [] }
        return (1..<nodes.count).map { i in
            GeoMath.distance(nodes[i - 1].lat, nodes[i - 1].lng, nodes[i].lat, nodes[i].lng)
        }
    }

    var totalMeters: Double { segmentMeters.reduce(0, +) }

    func baseSpeed(segment: Int) -> Double {
        guard segment >= 0, segment < nodes.count else { return globalSpeed }
        let v = nodes[segment].speedMps
        return v > 0 ? v : globalSpeed
    }

    var summary: String {
        "\(nodes.count) 个节点 · \(max(0, nodes.count - 1)) 段 · \(Int(totalMeters.rounded())) m"
    }

    var previewTrack: Track {
        var t = Track(name: name, points: nodes.enumerated().map { i, n in
            TrackPoint(t: i * 1000, lat: n.lat, lng: n.lng)
        })
        t.intervalMs = 1000
        return t
    }
}