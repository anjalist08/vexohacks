import Foundation

/// Tracking on the phone (no laptop): a Swift port of ImTimTong's wrist tracker
/// (tracker/wrist.py), tuned on the team's real wrist walks.
/// 1. The gyro bias is calibrated only on real stillness (0.3 s of a quiet gyro, median),
///    and re-estimated whenever the band is still. Nothing is tracked before that.
/// 2. Heading = the gyro projected on gravity, integrated, then a 2 s rolling median, so arm
///    swing does not bend the line. It is held on a 90° grid and moves to another grid line
///    only after staying 50° away for 0.5 s.
/// 3. Steps from the band's own counter ("band", the team's default), or from footfalls in
///    the accelerometer ("accel").
/// Heading is clockwise from the direction you faced at "start route"; +y is that direction.
final class PhoneTracker {
    var stepLength = 0.7
    var snapTurns = true
    var stepSource = "band"

    private(set) var running = false
    private(set) var calibrated = false
    private(set) var x = 0.0, y = 0.0
    private(set) var heading = 0.0          // walking heading on the 90° grid (unwrapped)
    private(set) var smooth = 0.0           // 2 s median heading (unwrapped)
    private(set) var facingRaw = 0.0        // where you face now (~0.2 s smoothing, unwrapped)
    private(set) var steps = 0
    private(set) var bias = 0.0
    private(set) var state = "still"
    private(set) var uncertainty = 0.0      // degrees of doubt; > 35 = "not sure where we are"

    var facing: Double { PhoneTracker.wrap(facingRaw) }
    var uncertain: Bool { uncertainty > 35 }

    var onPoint: ((Double, Double, Double, Int, Double) -> Void)?   // x, y, heading, steps, time

    private var gravity: [Double]?
    private var lastMotion: Double?
    private var unwrapped = 0.0
    private var window: [(Double, Double)] = []
    private var quiet: [Double] = []
    private var awaySince: Double?
    private var lastSteps: Int?
    private var accSmooth: Double?
    private var accArmed = true
    private var accLast = -1e9

    static func wrap(_ a: Double) -> Double {
        var v = (a + 180).truncatingRemainder(dividingBy: 360)
        if v < 0 { v += 360 }
        let r = v - 180
        return r == -180 ? 180 : r
    }

    private static func median(_ v: [Double]) -> Double {
        let s = v.sorted()
        guard !s.isEmpty else { return 0 }
        return s.count % 2 == 1 ? s[s.count / 2] : (s[s.count / 2 - 1] + s[s.count / 2]) / 2
    }

    func start(at t: Double) {
        running = true; calibrated = false
        x = 0; y = 0; heading = 0; smooth = 0; facingRaw = 0; unwrapped = 0; steps = 0; bias = 0
        uncertainty = 0; gravity = nil; lastMotion = nil; window = []; quiet = []; awaySince = nil
        lastSteps = nil; accSmooth = nil; accArmed = true; accLast = -1e9
        onPoint?(0, 0, 0, 0, t)
    }

    func stop() { running = false }
    func resume() { running = true; lastMotion = nil }

    /// One motion sample: acceleration in g, turning speed in degrees/second.
    func motion(t: Double, ax: Double, ay: Double, az: Double, gx: Double, gy: Double, gz: Double) {
        guard running else { return }
        let dt = lastMotion.map { max(0, min(0.2, t - $0)) } ?? 0
        lastMotion = t
        let accel = (ax * ax + ay * ay + az * az).squareRoot()
        var g = gravity ?? [ax, ay, az]
        if gravity != nil { g = [g[0] + 0.05 * (ax - g[0]), g[1] + 0.05 * (ay - g[1]), g[2] + 0.05 * (az - g[2])] }
        gravity = g
        let norm = (g[0] * g[0] + g[1] * g[1] + g[2] * g[2]).squareRoot()
        if accel < 0.3 || accel > 2.5 || norm < 0.3 || norm > 2.5 { uncertainty += max(4, 80 * dt) }
        guard norm >= 0.3 else { return }
        let yaw = (gx * g[0] + gy * g[1] + gz * g[2]) / norm

        // 1. calibrate (and keep refining) only when truly still
        if (gx * gx + gy * gy + gz * gz).squareRoot() < 6 {
            quiet.append(yaw)
            if quiet.count > 15 { quiet.removeFirst() }
            if quiet.count == 15 {
                let m = PhoneTracker.median(quiet)
                if !calibrated { bias = m; calibrated = true } else { bias += 0.02 * (m - bias) }
            }
        } else {
            quiet = []
        }
        guard calibrated else { return }

        // 2. integrate (+ yaw = left = lower heading), quick facing, 2 s median, grid
        unwrapped -= (yaw - bias) * dt
        if dt > 0 { facingRaw += (1 - exp(-dt / 0.2)) * (unwrapped - facingRaw) }
        window.append((t, unwrapped))
        while let first = window.first, t - first.0 > 2 { window.removeFirst() }
        smooth = PhoneTracker.median(window.map(\.1))
        updateGrid(t)

        // 3. footfalls, when steps come from the accelerometer
        if stepSource == "accel" && footfall(t, accel) { advance(1, t) }
    }

    private func updateGrid(_ t: Double) {
        guard snapTurns else { heading = smooth; return }
        if abs(smooth - heading) <= 50 { awaySince = nil; return }
        guard let since = awaySince else { awaySince = t; return }
        if t - since >= 0.5 {
            heading = 90 * (smooth / 90).rounded()
            awaySince = nil
        }
    }

    private func footfall(_ t: Double, _ mag: Double) -> Bool {
        let s = accSmooth.map { $0 + 0.35 * (mag - $0) } ?? mag
        accSmooth = s
        if accArmed && s > 1.12 && t - accLast >= 0.28 { accArmed = false; accLast = t; return true }
        if s < 1.03 { accArmed = true }
        return false
    }

    private func advance(_ n: Int, _ t: Double) {
        uncertainty += 0.4 * Double(n)
        if snapTurns && awaySince == nil {          // walking clearly off the grid, not mid-turn
            let off = abs(smooth - heading)
            if off > 30 { uncertainty += 0.25 * (off - 30) * Double(n) }
        }
        let d = Double(n) * stepLength
        let h = heading * .pi / 180
        x += d * sin(h)
        y += d * cos(h)
        steps += n
        onPoint?(x, y, PhoneTracker.wrap(heading), steps, t)
    }

    /// One activity reading: the band's lifetime step total and still / walk / run.
    func activity(t: Double, total: Int, state: String) {
        guard running else { return }
        self.state = state
        guard let last = lastSteps, calibrated else { lastSteps = total; return }
        let new = total - last
        lastSteps = total
        guard new > 0 else { return }
        if stepSource == "band" { advance(new, t) }
    }

    /// You are at a known spot: reset position and heading, clear the doubt (cancels drift).
    func reanchor(x: Double, y: Double, heading h: Double, t: Double) {
        self.x = x; self.y = y
        let w = PhoneTracker.wrap(h)
        heading = w; smooth = w; unwrapped = w; facingRaw = w
        window = []; awaySince = nil; uncertainty = 0
        onPoint?(x, y, w, steps, t)
    }
}
