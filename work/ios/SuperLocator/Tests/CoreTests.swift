//
//  CoreTests.swift
//  SuperLocator 单元测试（无需真机、无需伴侣程序，模拟器内即可跑）
//
//  覆盖：
//   1) golden.json 三方一致性（几何 + Catmull-Rom 插值，向量由 work/ios/tools/make_golden.py 生成）
//   2) 抖动上界 = 1.5R、radius=0 恒为零、bias/bearing 的方向性
//   3) Track 的 JSON 往返、时间轴归一化、距离
//   4) 预设路径的每段基准速度与偏移区间
//   5) 轨迹库 / 预设路径库的落盘读写（分组、改名、移动、删除）
//

import XCTest
import CoreGraphics
@testable import SuperLocator

final class CoreTests: XCTestCase {

    // MARK: - golden.json

    struct GoldenDistance: Decodable { let lat1, lng1, lat2, lng2, meters: Double }
    struct GoldenBearing: Decodable { let lat1, lng1, lat2, lng2, deg: Double }
    struct GoldenOffset: Decodable { let lat, lng, east, north, outLat, outLng: Double }
    struct GoldenAlong: Decodable { let lat1, lng1, lat2, lng2, fraction, outLat, outLng: Double }
    struct GoldenInterp: Decodable {
        struct Case: Decodable { let ms: Double; let outLat, outLng: Double }
        let points: [[Double]]
        let cases: [Case]
    }
    struct Golden: Decodable {
        let distance: [GoldenDistance]
        let bearing: [GoldenBearing]
        let offset: [GoldenOffset]
        let pointAlong: [GoldenAlong]
        let interpolate: GoldenInterp
    }

    private func golden() throws -> Golden {
        guard let url = Bundle(for: CoreTests.self).url(forResource: "golden", withExtension: "json") else {
            throw XCTSkip("golden.json 未打进测试包（检查 project.yml 里 Tests 目录是否作为资源）")
        }
        return try JSONDecoder().decode(Golden.self, from: Data(contentsOf: url))
    }

    func testGoldenDistance() throws {
        let g = try golden()
        XCTAssertGreaterThan(g.distance.count, 3)
        for c in g.distance {
            let v = GeoMath.distance(c.lat1, c.lng1, c.lat2, c.lng2)
            XCTAssertEqual(v, c.meters, accuracy: 1e-6, "distance \(c.lat1),\(c.lng1)")
        }
    }

    func testGoldenBearing() throws {
        let g = try golden()
        for c in g.bearing {
            let v = GeoMath.bearing(c.lat1, c.lng1, c.lat2, c.lng2)
            XCTAssertEqual(v, c.deg, accuracy: 1e-6, "bearing \(c.lat1),\(c.lng1)")
        }
    }

    func testGoldenOffset() throws {
        let g = try golden()
        for c in g.offset {
            let (lat, lng) = GeoMath.offset(c.lat, c.lng, eastMeters: c.east, northMeters: c.north)
            XCTAssertEqual(lat, c.outLat, accuracy: 1e-9, "offset lat e=\(c.east) n=\(c.north)")
            XCTAssertEqual(lng, c.outLng, accuracy: 1e-9, "offset lng e=\(c.east) n=\(c.north)")
        }
    }

    func testGoldenPointAlong() throws {
        let g = try golden()
        for c in g.pointAlong {
            let (lat, lng) = GeoMath.pointAlong(c.lat1, c.lng1, c.lat2, c.lng2, fraction: c.fraction)
            XCTAssertEqual(lat, c.outLat, accuracy: 1e-9, "along f=\(c.fraction)")
            XCTAssertEqual(lng, c.outLng, accuracy: 1e-9, "along f=\(c.fraction)")
        }
    }

    func testGoldenInterpolate() throws {
        let g = try golden()
        let pts = g.interpolate.points.compactMap { row -> TrackPoint? in
            guard row.count == 3 else { return nil }
            return TrackPoint(t: Int(row[0]), lat: row[1], lng: row[2])
        }
        XCTAssertEqual(pts.count, g.interpolate.points.count)
        var track = Track(name: "golden", points: pts)
        track.intervalMs = 1000
        for c in g.interpolate.cases {
            let (lat, lng) = GeoMath.interpolate(track, atMs: c.ms)
            XCTAssertEqual(lat, c.outLat, accuracy: 1e-9, "interp ms=\(c.ms)")
            XCTAssertEqual(lng, c.outLng, accuracy: 1e-9, "interp ms=\(c.ms)")
        }
    }

    // MARK: - 抖动

    func testJitterZeroRadiusStaysZero() {
        let j = Jitter(radius: 0, bias: 0.8, bearing: 90)
        XCTAssertFalse(j.isActive)
        for i in 0..<400 {
            let v = j.step(nowMs: Double(i) * 100)
            XCTAssertEqual(v.dx, 0, accuracy: 1e-12)
            XCTAssertEqual(v.dy, 0, accuracy: 1e-12)
        }
        XCTAssertEqual(j.describe, "无抖动")
    }

    func testJitterStaysWithinBound() {
        let radius = 50.0
        let j = Jitter(radius: radius, bias: 0.55, bearing: nil)
        var peak = 0.0
        for i in 0..<3000 {
            let v = j.step(nowMs: Double(i) * 100)
            peak = max(peak, hypot(v.dx, v.dy))
        }
        XCTAssertLessThanOrEqual(peak, radius * 1.5 + 0.001, "峰值 \(peak) 超过 1.5R")
        XCTAssertGreaterThan(peak, radius * 0.05, "抖动几乎为 0，公式没生效")
    }

    func testJitterBiasDirection() {
        // bearing=90° 表示东，bias=0.9 → 采样期间整体偏东
        let j = Jitter(radius: 40, bias: 0.9, bearing: 90)
        var eastSum = 0.0
        var n = 0
        for i in 0..<900 {
            let v = j.step(nowMs: Double(i) * 100)
            if i > 20 { eastSum += v.dx; n += 1 }
        }
        XCTAssertGreaterThan(eastSum / Double(max(1, n)), 0, "带 90° 偏向的抖动平均没有偏东")
    }

    // MARK: - Track

    private func sampleTrack() -> Track {
        let base = 1_700_000_000_000
        let pts = (0..<6).map { i in
            TrackPoint(t: base + i * 500,
                       lat: 36.710210 + Double(i) * 0.0002,
                       lng: 117.021550 + Double(i) * 0.0003)
        }
        return Track(name: "单元测试轨迹", points: pts)
    }

    func testTrackJsonRoundTrip() throws {
        let t = sampleTrack()
        let data = try JSONEncoder().encode(t)
        let back = try JSONDecoder().decode(Track.self, from: data)
        XCTAssertEqual(back.points.count, t.points.count)
        XCTAssertEqual(back.points[3].lat, t.points[3].lat, accuracy: 1e-12)
        XCTAssertEqual(back.points[3].lng, t.points[3].lng, accuracy: 1e-12)
        XCTAssertEqual(back.intervalMs, t.intervalMs)
    }

    func testNormalizeTimelineIsMonotonic() {
        var t = sampleTrack()
        t.points[2].t = t.points[1].t          // 制造重复时间戳
        t.points[3].t = t.points[0].t
        t.normalizeTimeline()
        XCTAssertEqual(t.points[0].t, 0)
        for i in 1..<t.points.count {
            XCTAssertGreaterThan(t.points[i].t, t.points[i - 1].t)
        }
    }

    func testTrackDistancePositive() {
        let t = sampleTrack()
        XCTAssertGreaterThan(t.distanceM, 1)
        XCTAssertEqual(t.durationMs, 2500)
    }

    func testGpxHasAllPoints() {
        let gpx = sampleTrack().toGPX()
        let count = gpx.components(separatedBy: "<trkpt").count - 1
        XCTAssertEqual(count, 6)
        XCTAssertTrue(gpx.contains("SuperLocator"))
    }

    // MARK: - 预设路径

    func testRouteSegmentSpeeds() {
        var r = PresetRoute()
        r.globalSpeed = 1.4
        r.offsetPercent = 20
        r.nodes = [
            RouteNode(lat: 36.710210, lng: 117.021550, speedMps: 0),   // 跟随全局
            RouteNode(lat: 36.711210, lng: 117.022550, speedMps: 3.0), // 单独设速
            RouteNode(lat: 36.712000, lng: 117.023800, speedMps: 2.0),
        ]
        XCTAssertEqual(r.segmentMeters.count, 2)
        XCTAssertGreaterThan(r.totalMeters, 100)
        XCTAssertEqual(r.baseSpeed(segment: 0), 1.4, accuracy: 1e-9)
        XCTAssertEqual(r.baseSpeed(segment: 1), 3.0, accuracy: 1e-9)
        XCTAssertEqual(r.previewTrack.points.count, 3)
    }

    // MARK: - 落盘存储

    func testTrackStoreCRUD() throws {
        let store = TrackStore()
        let group = store.createGroup("单元测试分组")
        let t = sampleTrack()
        store.saveTrack(t, groupId: group.id)

        XCTAssertEqual(store.count(inGroup: group.id), 1)
        let loaded = store.loadTrack(t.id, groupId: group.id)
        XCTAssertEqual(loaded?.points.count, t.points.count)

        store.renameTrack(t.id, groupId: group.id, to: "改过名的轨迹")
        XCTAssertEqual(store.meta(t.id)?.name, "改过名的轨迹")

        store.moveTrack(t.id, from: group.id, to: TrackStore.defaultGroupId)
        XCTAssertEqual(store.count(inGroup: group.id), 0)
        XCTAssertNotNil(store.loadTrack(t.id, groupId: TrackStore.defaultGroupId))

        store.deleteTrack(t.id, groupId: TrackStore.defaultGroupId)
        XCTAssertNil(store.loadTrack(t.id, groupId: TrackStore.defaultGroupId))

        store.deleteGroup(group.id)
        XCTAssertFalse(store.groups.contains { $0.id == group.id })
    }

    func testRouteStoreCRUD() throws {
        let store = RouteStore()
        var r = PresetRoute()
        r.name = "单元测试路径"
        r.nodes = [
            RouteNode(lat: 36.710210, lng: 117.021550, speedMps: 0),
            RouteNode(lat: 36.712000, lng: 117.023800, speedMps: 0),
        ]
        store.save(r)
        XCTAssertNotNil(store.load(r.id))
        XCTAssertEqual(store.load(r.id)?.nodes.count, 2)

        store.delete(r.id)
        XCTAssertNil(store.load(r.id))
    }

    // MARK: - 伴侣程序的 JSON 契约（与 Android 三端一致）

    func testCompanionPayloadShape() throws {
        let t = sampleTrack()
        let data = try JSONEncoder().encode(t)
        let obj = try JSONSerialization.jsonObject(with: data) as? [String: Any]
        XCTAssertNotNil(obj)
        XCTAssertNotNil(obj?["points"])
        let points = obj?["points"] as? [[Any]]
        XCTAssertEqual(points?.count, t.points.count)
        XCTAssertEqual(points?.first?.count, 3, "点位必须是 [t,lat,lng] 三元组")
    }

    // MARK: - 激活码（格式层，密钥在电脑端）

    func testLicenseParseAndPretty() {
        let code = "01C6S-H94W6-DFR0T-N95C2"
        XCTAssertEqual(CodeMath.clean(code).count, 20)
        let parsed = CodeMath.parse(code)
        XCTAssertNotNil(parsed)
        XCTAssertEqual(parsed?.serial, 1)
        XCTAssertEqual(CodeMath.pretty(CodeMath.clean(code)), code)
    }

    func testLicenseRejectsBadInput() {
        XCTAssertNil(CodeMath.parse("01C6S-H94W6-DFR0T-N95C"))     // 少一位
        XCTAssertNil(CodeMath.parse("01C6S-H94W6-DFR0T-N95C2X"))   // 多一位
        XCTAssertNil(CodeMath.parse("IIIII-IIIII-IIIII-IIIII"))     // 字母表里没有 I
    }

    func testLicenseSerialIsInPayload() {
        // Swift 的 Int 装不下 100 bit，这里只按格式拼：前 2 字符 = 10 bit 串号，后 18 字符当 MAC 填空
        for serial in [1, 7, 42, 999, 1023] {
            var chars: [Character] = []
            for shift in stride(from: 5, through: 0, by: -5) {
                chars.append(CodeMath.alphabet[(serial >> shift) & 31])
            }
            let code = String(chars) + String(repeating: "0", count: 18)
            XCTAssertEqual(code.count, 20)
            XCTAssertEqual(CodeMath.serial(of: code), serial)
        }
    }

    func testLicenseStoreRoundTrip() {
        let store = LicenseStore.shared
        let before = store.code
        store.save("01C6S-H94W6-DFR0T-N95C2")
        XCTAssertTrue(store.wellFormed)
        XCTAssertFalse(store.activated)          // 电脑端还没确认
        store.updateServer(active: true, serial: 1)
        XCTAssertTrue(store.activated)
        store.updateServer(active: false, serial: 1)
        XCTAssertFalse(store.activated)          // 吊销即时反映
        if before.isEmpty { store.clear() } else { store.save(before) }
    }
}
