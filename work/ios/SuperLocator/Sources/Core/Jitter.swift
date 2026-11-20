//
//  Jitter.swift
//  「随机值 / 权重偏于」—— 与 Android 版 Jitter.java 同一套公式：
//    baseMag   = radius * bias * (0.5 + 0.5u)
//    spread    = 180 * (1 - bias) + 12        (bias ≥ 0.999 → ±3°)
//    wobbleMag = radius * (1 - 0.65 bias) * rayleigh(σ=0.55)
//    target    = 极坐标(baseBearing, baseMag) + 极坐标(θ, wobbleMag)
//    每 4~9 秒重采样，输出一阶低通 k = 1 - exp(-dt/1.2)，限幅 radius*1.5
//

import Foundation

final class Jitter {
    private(set) var radius: Double
    private(set) var bias: Double
    private(set) var baseBearing: Double
    private var baseMag: Double

    private var target = CGVector(dx: 0, dy: 0)
    private var current = CGVector(dx: 0, dy: 0)
    private var nextResampleMs: Double = 0
    private var lastMs: Double = 0

    init(radius: Double = 0, bias: Double = 0, bearing: Double? = nil) {
        self.radius = max(0, radius)
        self.bias = GeoMath.clamp(bias, 0, 1)
        self.baseBearing = bearing ?? Double.random(in: 0..<360)
        self.baseMag = self.radius * self.bias * (0.5 + 0.5 * Double.random(in: 0...1))
    }

    var isActive: Bool { radius > 0.01 }

    func configure(radius: Double, bias: Double, bearing: Double?) {
        self.radius = max(0, radius)
        self.bias = GeoMath.clamp(bias, 0, 1)
        if let bearing { self.baseBearing = bearing }
        self.baseMag = self.radius * self.bias * (0.5 + 0.5 * Double.random(in: 0...1))
        self.nextResampleMs = 0
        self.target = .zero
        self.current = .zero
    }

    private func resample(_ nowMs: Double) {
        let spread = 180 * (1 - bias) + (bias >= 0.999 ? 3 : 12)
        let theta = baseBearing + gaussian(0, spread)
        // Rayleigh(σ=0.55)：-2σ²ln(u) 开方
        let u = max(1e-6, Double.random(in: 0...1))
        let rayleigh = 0.55 * sqrt(-2 * log(u))
        let mag = radius * (1 - 0.65 * bias) * rayleigh

        let baseEast = baseMag * sin(baseBearing * .pi / 180)
        let baseNorth = baseMag * cos(baseBearing * .pi / 180)
        target = CGVector(dx: baseEast + mag * sin(theta * .pi / 180),
                          dy: baseNorth + mag * cos(theta * .pi / 180))
        nextResampleMs = nowMs + Double.random(in: 4000...9000)
    }

    /// 返回当前东向 / 北向偏移（米）
    func step(nowMs: Double) -> CGVector {
        guard radius > 0 else { return .zero }
        if nextResampleMs == 0 {
            resample(nowMs)
            lastMs = nowMs
            return target
        }
        let dt = max(0, (nowMs - lastMs) / 1000)
        lastMs = nowMs
        let k = dt > 0 ? 1 - exp(-dt / 1.2) : 0
        current.dx += (target.dx - current.dx) * k
        current.dy += (target.dy - current.dy) * k
        let limit = radius * 1.5
        let mag = hypot(current.dx, current.dy)
        if mag > limit, mag > 0 {
            current.dx *= limit / mag
            current.dy *= limit / mag
        }
        if nowMs >= nextResampleMs { resample(nowMs) }
        return current
    }

    func reset() {
        target = .zero
        current = .zero
        nextResampleMs = 0
        baseBearing = Double.random(in: 0..<360)
        baseMag = radius * bias * (0.5 + 0.5 * Double.random(in: 0...1))
    }

    var describe: String {
        guard radius > 0.01 else { return "无抖动" }
        let side = bias >= 0.9 ? "强偏向" : (bias < 0.05 ? "" : "偏向")
        return String(format: "半径 %.0fm · %@%.0f° · 权重 %.0f%%", radius, side, baseBearing, bias * 100)
    }

    private func gaussian(_ mean: Double, _ sigma: Double) -> Double {
        let u1 = max(1e-9, Double.random(in: 0...1))
        let u2 = Double.random(in: 0...1)
        return mean + sigma * sqrt(-2 * log(u1)) * cos(2 * .pi * u2)
    }
}