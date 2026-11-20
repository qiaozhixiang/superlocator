//
//  GeoMath.swift
//  与 Android 版 GeoMath.java / 伴侣程序 Geo 类同一套公式（误差 < 0.1%）
//

import Foundation

enum GeoMath {
    static let earthRadius = 6_371_008.8

    static func distance(_ lat1: Double, _ lng1: Double, _ lat2: Double, _ lng2: Double) -> Double {
        let p1 = lat1 * .pi / 180
        let p2 = lat2 * .pi / 180
        let dp = p2 - p1
        let dl = (lng2 - lng1) * .pi / 180
        let a = sin(dp / 2) * sin(dp / 2) + cos(p1) * cos(p2) * sin(dl / 2) * sin(dl / 2)
        return 2 * earthRadius * asin(min(1, sqrt(a)))
    }

    static func bearing(_ lat1: Double, _ lng1: Double, _ lat2: Double, _ lng2: Double) -> Double {
        let p1 = lat1 * .pi / 180
        let p2 = lat2 * .pi / 180
        let dl = (lng2 - lng1) * .pi / 180
        let y = sin(dl) * cos(p2)
        let x = cos(p1) * sin(p2) - sin(p1) * cos(p2) * cos(dl)
        return (atan2(y, x) * 180 / .pi + 360).truncatingRemainder(dividingBy: 360)
    }

    /// 以米为单位的东向 / 北向偏移，返回 (lat, lng)
    static func offset(_ lat: Double, _ lng: Double, eastMeters: Double, northMeters: Double) -> (Double, Double) {
        let dLat = northMeters / 111_132.92
        let cosLat = max(0.02, cos(lat * .pi / 180))
        let dLng = eastMeters / (111_132.92 * cosLat)
        return (lat + dLat, lng + dLng)
    }

    /// 线段上按比例取点
    static func pointAlong(_ lat1: Double, _ lng1: Double, _ lat2: Double, _ lng2: Double, fraction: Double) -> (Double, Double) {
        let d = distance(lat1, lng1, lat2, lng2)
        if d < 1e-6 { return (lat1, lng1) }
        let b = bearing(lat1, lng1, lat2, lng2)
        let east = d * fraction * sin(b * .pi / 180)
        let north = d * fraction * cos(b * .pi / 180)
        return offset(lat1, lng1, eastMeters: east, northMeters: north)
    }

    /// Catmull-Rom 平滑插值（与 Android ReplayEngine.interpolate 一致）
    static func interpolate(_ track: Track, atMs ms: Double) -> (Double, Double) {
        let pts = track.points
        guard !pts.isEmpty else { return (0, 0) }
        if ms <= Double(pts[0].t) { return (pts[0].lat, pts[0].lng) }
        if ms >= Double(pts[pts.count - 1].t) { return (pts[pts.count - 1].lat, pts[pts.count - 1].lng) }

        var lo = 0, hi = pts.count - 1
        while lo + 1 < hi {
            let mid = (lo + hi) / 2
            if Double(pts[mid].t) <= ms { lo = mid } else { hi = mid }
        }
        let span = max(1, pts[lo + 1].t - pts[lo].t)
        let u = (ms - Double(pts[lo].t)) / Double(span)
        let p0 = pts[max(0, lo - 1)]
        let p1 = pts[lo]
        let p2 = pts[lo + 1]
        let p3 = pts[min(pts.count - 1, lo + 2)]
        let u2 = u * u, u3 = u2 * u
        let lat = 0.5 * (2 * p1.lat + (-p0.lat + p2.lat) * u
                         + (2 * p0.lat - 5 * p1.lat + 4 * p2.lat - p3.lat) * u2
                         + (-p0.lat + 3 * p1.lat - 3 * p2.lat + p3.lat) * u3)
        let lng = 0.5 * (2 * p1.lng + (-p0.lng + p2.lng) * u
                         + (2 * p0.lng - 5 * p1.lng + 4 * p2.lng - p3.lng) * u2
                         + (-p0.lng + 3 * p1.lng - 3 * p2.lng + p3.lng) * u3)
        return (lat, lng)
    }

    static func clamp(_ v: Double, _ lo: Double, _ hi: Double) -> Double {
        min(hi, max(lo, v))
    }
}