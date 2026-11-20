//
//  Engines.swift
//  注入会话、录制器、轨迹重放引擎、预设路径引擎。
//  结构对应 Android 版 TrackRuntime + Recorder + ReplayEngine + RouteEngine。
//

import Foundation
import Combine
import SwiftUI

struct Coordinate: Equatable {
    var lat: Double
    var lng: Double
}

// MARK: - 注入会话（全局单例，UI 与引擎都看它）

final class InjectionSession: ObservableObject {
    static let shared = InjectionSession()

    @Published var position: Coordinate = Coordinate(lat: 36.667662, lng: 117.027707)
    @Published var hasPosition = false
    @Published var isPlaying = false
    @Published var isPaused = false
    @Published var progress: Double = 0
    @Published var speedMps: Double = 0
    @Published var segmentText = ""
    @Published var jitterText = "无抖动"
    @Published var statusMessage = "待机"
    @Published var isRecording = false
    @Published var recordedPoints = 0

    weak var client: CompanionClient?
    let recorder = Recorder()
    private(set) var jitter = Jitter()
    private var lastStatusAt = Date.distantPast

    func note(_ message: String) {
        statusMessage = message
    }

    func configureJitter(radius: Double, bias: Double, bearing: Double?) {
        jitter.configure(radius: radius, bias: bias, bearing: bearing)
        jitterText = jitter.describe
    }

    /// 把基准坐标（轨迹/路径上的点）加抖动后写入设备
    func inject(base: Coordinate) {
        let nowMs = Date().timeIntervalSince1970 * 1000
        let off = jitter.step(nowMs: nowMs)
        let (lat, lng) = GeoMath.offset(base.lat, base.lng, eastMeters: off.dx, northMeters: off.dy)
        position = Coordinate(lat: lat, lng: lng)
        hasPosition = true
        client?.setLocation(lat: lat, lng: lng)

        if recorder.isRunning {
            recorder.offer(t: Int(nowMs), coord: position)
            recordedPoints = recorder.points.count
        }
    }

    func status(_ text: String) {
        guard Date().timeIntervalSince(lastStatusAt) > 0.25 else { return }
        lastStatusAt = Date()
        statusMessage = text
    }
}

// MARK: - 录制器

final class Recorder {
    private(set) var isRunning = false
    private(set) var points: [TrackPoint] = []
    var intervalMs: Int = 500
    var minMoveMeters: Double = 1.0
    var minKeepMs: Int = 5000
    let maxPoints = 200_000

    private var lastKept: TrackPoint?
    private var startMs: Int = 0
    private var groupId = TrackStore.defaultGroupId
    private var name = ""

    func configure(intervalMs: Int, minMoveMeters: Double) {
        self.intervalMs = max(100, intervalMs)
        self.minMoveMeters = max(0, minMoveMeters)
    }

    func start(name: String, groupId: String, nowMs: Int) {
        self.name = name
        self.groupId = groupId
        points.removeAll()
        lastKept = nil
        startMs = nowMs
        isRunning = true
    }

    func offer(t: Int, coord: Coordinate) {
        guard isRunning else { return }
        let rel = t - startMs
        let p = TrackPoint(t: rel, lat: coord.lat, lng: coord.lng)
        guard let last = lastKept else {
            points.append(p)
            lastKept = p
            return
        }
        let moved = GeoMath.distance(last.lat, last.lng, p.lat, p.lng)
        if moved >= minMoveMeters || rel - last.t >= minKeepMs {
            points.append(p)
            lastKept = p
        }
        if points.count >= maxPoints { isRunning = false }
    }

    func stop() -> Track? {
        isRunning = false
        guard points.count >= 2 else { return nil }
        var track = Track(name: name.isEmpty ? "轨迹 " + Self.stamp() : name,
                          groupId: groupId,
                          points: points)
        track.normalizeTimeline()
        return track
    }

    static func stamp() -> String {
        let f = DateFormatter()
        f.dateFormat = "MM-dd HH:mm:ss"
        return f.string(from: Date())
    }
}

// MARK: - 轨迹重放引擎

final class ReplayEngine: ObservableObject {
    private var timer: Timer?
    private var track: Track?
    private var startedAt = Date()
    private var pausedElapsed: Double = 0
    private var speed: Double = 1
    private var loop = false

    var onFinish: (() -> Void)?

    var isRunning: Bool { timer != nil }

    func start(track: Track, speed: Double, loop: Bool, radius: Double, bias: Double, bearing: Double?) {
        stop()
        self.track = track
        self.speed = GeoMath.clamp(speed, 0.1, 20)
        self.loop = loop
        startedAt = Date()
        pausedElapsed = 0
        let session = InjectionSession.shared
        session.configureJitter(radius: radius, bias: bias, bearing: bearing)
        session.isPlaying = true
        session.isPaused = false
        session.progress = 0

        if let first = track.points.first {
            session.inject(base: Coordinate(lat: first.lat, lng: first.lng))
        }
        timer = Timer.scheduledTimer(withTimeInterval: 0.1, repeats: true) { [weak self] _ in
            self?.tick()
        }
        RunLoop.main.add(timer!, forMode: .common)
    }

    private func tick() {
        guard let track, !track.points.isEmpty else { return }
        let session = InjectionSession.shared
        if session.isPaused {
            pausedElapsed += 0.1
            return
        }
        let elapsed = Date().timeIntervalSince(startedAt) + pausedElapsed
        var ms = elapsed * 1000 * speed
        let duration = Double(track.durationMs)

        if duration > 0, ms > duration {
            if loop {
                ms = ms.truncatingRemainder(dividingBy: duration)
                startedAt = Date()
                pausedElapsed = 0
            } else {
                ms = duration
            }
        }
        session.progress = duration > 0 ? min(1, ms / duration) : 0
        let base = GeoMath.interpolate(track, atMs: ms)
        session.inject(base: Coordinate(lat: base.0, lng: base.1))
        let seg = sector(ms: ms, track: track)
        session.speedMps = seg.speed
        session.segmentText = String(format: "第 %.0f/%.0f 米", seg.travel, seg.total)
        session.status(String(format: "重放中 %.0f%% · %.1f m/s", session.progress * 100, seg.speed))

        if ms >= duration, !loop {
            stop(finished: true)
        }
    }

    private func sector(ms: Double, track: Track) -> (speed: Double, travel: Double, total: Double) {
        guard track.points.count > 1 else { return (0, 0, 0) }
        let total = track.distanceM
        var travel = 0.0
        for i in 1..<track.points.count {
            let a = track.points[i - 1], b = track.points[i]
            let d = GeoMath.distance(a.lat, a.lng, b.lat, b.lng)
            if Double(b.t) >= ms {
                let frac = (ms - Double(a.t)) / Double(max(1, b.t - a.t))
                travel += d * frac
                let dt = Double(max(1, b.t - a.t)) / 1000
                return (d / dt, travel, total)
            }
            travel += d
        }
        return (0, travel, total)
    }

    func pause() {
        InjectionSession.shared.isPaused = true
        InjectionSession.shared.status("已暂停")
    }

    func resume() {
        InjectionSession.shared.isPaused = false
        InjectionSession.shared.status("继续重放")
    }

    func stop(finished: Bool = false) {
        timer?.invalidate()
        timer = nil
        let session = InjectionSession.shared
        session.isPlaying = false
        session.isPaused = false
        if finished {
            session.progress = 1
            session.status("重放到终点")
            onFinish?()
        } else {
            session.status("已停止")
        }
    }
}

// MARK: - 预设路径引擎

final class RouteEngine: ObservableObject {
    private var timer: Timer?
    private var route: PresetRoute?
    private var segLengths: [Double] = []
    private var cumulative: [Double] = []
    private var total: Double = 0
    private var travel: Double = 0
    private var segment = 0
    private var segmentSpeed: Double = 0
    private var segmentUntil = Date.distantPast
    private var lastTick = Date()
    private var loop = false

    var isRunning: Bool { timer != nil }

    func start(route: PresetRoute, loop: Bool, radius: Double, bias: Double, bearing: Double?) {
        stop()
        guard route.nodes.count >= 2 else { return }
        self.route = route
        self.loop = loop
        segLengths = route.segmentMeters
        cumulative = [0]
        for len in segLengths { cumulative.append(cumulative.last! + len) }
        total = cumulative.last ?? 0
        travel = 0
        segment = 0
        segmentSpeed = 0
        lastTick = Date()

        let session = InjectionSession.shared
        session.configureJitter(radius: radius, bias: bias, bearing: bearing)
        session.isPlaying = true
        session.isPaused = false
        session.progress = 0
        if let first = route.nodes.first {
            session.inject(base: Coordinate(lat: first.lat, lng: first.lng))
        }
        timer = Timer.scheduledTimer(withTimeInterval: 0.1, repeats: true) { [weak self] _ in
            self?.tick()
        }
        RunLoop.main.add(timer!, forMode: .common)
        session.status("预设路径开始：\(route.name)")
    }

    private func tick() {
        guard let route, total > 0 else { return }
        let session = InjectionSession.shared
        let now = Date()
        if session.isPaused {
            lastTick = now
            return
        }
        let dt = min(0.5, max(0, now.timeIntervalSince(lastTick)))
        lastTick = now

        if now >= segmentUntil || segmentSpeed <= 0 {
            let factor = 1 + Double.random(in: -1...1) * route.offsetPercent / 100
            segmentSpeed = GeoMath.clamp(route.baseSpeed(segment: segment) * factor, 0.2, 25)
            segmentUntil = now.addingTimeInterval(2.5)
        }
        travel += segmentSpeed * dt
        if travel >= total {
            if loop {
                travel = travel.truncatingRemainder(dividingBy: total)
            } else {
                travel = total
            }
        }
        var seg = 0
        while seg + 1 < cumulative.count, cumulative[seg + 1] < travel { seg += 1 }
        if seg != segment {
            segment = seg
            segmentUntil = .distantPast
        }
        let length = seg < segLengths.count ? segLengths[seg] : 0
        let frac = length <= 0 ? 0 : (travel - cumulative[seg]) / length
        let a = route.nodes[seg]
        let b = route.nodes[min(seg + 1, route.nodes.count - 1)]
        let base = GeoMath.pointAlong(a.lat, a.lng, b.lat, b.lng, fraction: GeoMath.clamp(frac, 0, 1))
        session.inject(base: Coordinate(lat: base.0, lng: base.1))
        session.progress = min(1, travel / total)
        session.speedMps = segmentSpeed
        session.segmentText = String(format: "第 %d/%d 段 · 已走 %.0f m", seg + 1, max(1, route.nodes.count - 1), travel)
        session.status(String(format: "预设路径 %.0f%% · %.1f m/s", session.progress * 100, segmentSpeed))

        if travel >= total, !loop {
            stop()
            session.progress = 1
            session.status("已到达终点")
        }
    }

    func pause() {
        InjectionSession.shared.isPaused = true
        InjectionSession.shared.status("已暂停")
    }

    func resume() {
        InjectionSession.shared.isPaused = false
    }

    func stop() {
        timer?.invalidate()
        timer = nil
        let session = InjectionSession.shared
        session.isPlaying = false
        session.isPaused = false
    }
}