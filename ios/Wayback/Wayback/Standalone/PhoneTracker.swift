import CoreMotion
import Foundation

/// Tracking on the phone (no laptop). Two modes, chosen by what is arriving:
///
/// FUSED (the iPhone's own sensors are running; the normal case)
///   Heading  The iPhone's gyro, projected on gravity and integrated (never the attitude's
///            "yaw" angle: that one jumps when the phone stands upright in a pocket).
///            While the phone is being handled (its tilt changes: taken out of a pocket, put
///            away, turned in the hand) its heading is not trusted; the band's heading carries
///            the route across that moment, and the phone is lined up again when it settles.
///   Steps    Counted at once from the bounce of each footfall in the iPhone's vertical
///            acceleration (three in rhythm start a walk, so picking the phone up is not a
///            step). Checked against two slower but steady counters: the band's own step
///            counter and Apple's pedometer. The count never falls behind them and never
///            runs more than a few steps ahead.
///   Stride   Apple's pedometer distance / steps, once it has seen enough steps.
///   Floor    The barometer: metres up or down since the route started.
///
/// BAND ONLY (no phone sensors, e.g. the simulator): the team's wrist tracker, unchanged.
///
/// Heading is clockwise from the direction you faced at "start route"; +y is that direction.
final class PhoneTracker {
    var stepLength = 0.7
    var snapTurns = true
    var stepSource = "band"                 // band-only mode: "band" or "accel"

    private(set) var running = false
    private(set) var x = 0.0, y = 0.0
    private(set) var heading = 0.0          // walking heading on the 90° grid (unwrapped)
    private(set) var smooth = 0.0           // smoothed heading the grid follows (unwrapped)
    private(set) var facingRaw = 0.0        // where you face now (unwrapped)
    private(set) var steps = 0
    private(set) var bias = 0.0
    private(set) var state = "still"
    private(set) var uncertainty = 0.0      // degrees of doubt; > 35 = "not sure where we are"
    private(set) var altitude = 0.0         // metres above where the route started (barometer)
    private(set) var handling = false       // the phone is being moved in the hand right now

    var facing: Double { PhoneTracker.wrap(facingRaw) }
    var uncertain: Bool { uncertainty > 35 }
    /// Ready to track: at once with the phone's sensors, else when the band's gyro is calibrated.
    var calibrated: Bool { phoneActive || bandCalibrated }
    var level: Int { Int((altitude / 3.2).rounded()) }
    var source: String { phoneActive ? (handling ? "band (phone moving)" : "iPhone + band") : "band" }

    var onPoint: ((Double, Double, Double, Int, Double) -> Void)?   // x, y, heading, steps, time

    // band
    private var bandCalibrated = false
    private var gravity: [Double]?
    private var lastMotion: Double?
    private var unwrapped = 0.0             // band heading, integrated
    private var bandSmooth = 0.0            // its 2 s median
    private var window: [(Double, Double)] = []
    private var quiet: [Double] = []
    private var awaySince: Double?
    private var lastSteps: Int?
    private var bandSince = 0               // band counter steps since the route started
    private var lastBandActivity = -1e9
    private var accSmooth: Double?
    private var accArmed = true
    private var accLast = -1e9

    // phone
    private let sensors = PhoneSensors()
    private var lastPhoneWall = -1e9
    private var lastPhoneStamp: Double?
    private var phoneHeading = 0.0          // integrated, unwrapped
    private var phoneOffset: Double?        // phoneHeading - fused, set when the phone lines up
    private var fused = 0.0
    private var fusedWindow: [(Double, Double)] = []
    private var history: [(t: Double, fused: Double, band: Double)] = []
    private var tiltSlow: [Double]?
    private var stableSince: Double?
    private var bridgeFused = 0.0, bridgeBand = 0.0
    private var upFast = 0.0, upSlow = 0.0
    private var stepArmed = true
    private var lastPeak = -1e9
    private var pending: [Double] = []
    private var walking = false
    private var detected = 0                // phone footfalls credited since the route started
    private var pedSince = 0
    private var pedAlive = false
    private var altitudeBase: Double?
    private var log = WalkLog()

    private var phoneActive: Bool { Date().timeIntervalSince1970 - lastPhoneWall < 1.0 }

    init() {
        sensors.onMotion = { [weak self] t, stamp, rate, g, up in self?.phone(t: t, stamp: stamp, rate: rate, gravity: g, up: up) }
        sensors.onPedometer = { [weak self] n, d in self?.pedometer(steps: n, distance: d) }
        sensors.onAltitude = { [weak self] m in self?.barometer(m) }
    }

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

    // MARK: lifecycle

    func start(at t: Double) {
        running = true; bandCalibrated = false
        x = 0; y = 0; heading = 0; smooth = 0; facingRaw = 0; unwrapped = 0; bandSmooth = 0; steps = 0; bias = 0
        uncertainty = 0; gravity = nil; lastMotion = nil; window = []; quiet = []; awaySince = nil
        lastSteps = nil; bandSince = 0; accSmooth = nil; accArmed = true; accLast = -1e9
        fused = 0; phoneOffset = nil; fusedWindow = []; history = []; tiltSlow = nil; handling = false; stableSince = nil
        upFast = 0; upSlow = 0; stepArmed = true; lastPeak = -1e9; pending = []; walking = false
        detected = 0; pedSince = 0; pedAlive = false; altitudeBase = nil; altitude = 0
        log.open()
        sensors.start()
        sensors.restartPedometer()
        onPoint?(0, 0, 0, 0, t)
    }

    func stop() { running = false; log.flush() }
    func resume() { running = true; lastMotion = nil; lastPhoneStamp = nil; sensors.start() }

    // MARK: the iPhone's sensors (50 a second)

    /// rate: turning speed about the vertical, degrees/second, clockwise seen from above.
    /// gravity: unit vector pointing down, in the phone's frame. up: vertical acceleration in g, gravity removed.
    private func phone(t: Double, stamp: Double, rate: Double, gravity gv: [Double], up: Double) {
        lastPhoneWall = t
        let dt = lastPhoneStamp.map { max(0, min(0.2, stamp - $0)) } ?? 0
        lastPhoneStamp = stamp
        phoneHeading += rate * dt
        guard running else { return }
        log.add("p,\(f3(t)),\(f2(rate)),\(f3(gv[0])),\(f3(gv[1])),\(f3(gv[2])),\(f3(up))")

        // Is the phone being handled? Its tilt (the direction of gravity in its own frame) moves a
        // lot when it leaves a pocket or is turned over, and hardly at all when the body turns.
        var slow = tiltSlow ?? gv
        let k = 1 - exp(-dt / 1.0)
        slow = [slow[0] + k * (gv[0] - slow[0]), slow[1] + k * (gv[1] - slow[1]), slow[2] + k * (gv[2] - slow[2])]
        tiltSlow = slow
        let n = (slow[0] * slow[0] + slow[1] * slow[1] + slow[2] * slow[2]).squareRoot()
        let cosTilt = n > 0.01 ? (gv[0] * slow[0] + gv[1] * slow[1] + gv[2] * slow[2]) / n : 1
        let tilt = acos(max(-1, min(1, cosTilt))) * 180 / .pi

        if phoneOffset == nil { phoneOffset = phoneHeading - fused }
        let bandFresh = bandCalibrated && t - (lastMotion ?? -1e9) < 1.0
        if !handling && tilt > 35 {
            handling = true; stableSince = nil
            // the turn of the wrist started a moment before the tilt crossed the line: go back 0.6 s
            let back = history.last(where: { $0.t <= t - 0.6 }) ?? history.first
            bridgeFused = back?.fused ?? fused
            bridgeBand = back?.band ?? bandSmooth
        }
        if handling {
            fused = bridgeFused + (bandFresh ? bandSmooth - bridgeBand : 0)   // the band carries the heading
            if tilt < 15 {
                if stableSince == nil { stableSince = t }
                else if t - stableSince! > 0.5 { handling = false; phoneOffset = phoneHeading - fused }
            } else {
                stableSince = nil
            }
        } else {
            fused = phoneHeading - (phoneOffset ?? 0)
        }
        history.append((t, fused, bandSmooth))
        while let first = history.first, t - first.t > 2 { history.removeFirst() }

        // walking direction: 1 s median (a pocket swings with the leg), then the 90° grid
        facingRaw = fused
        fusedWindow.append((t, fused))
        while let first = fusedWindow.first, t - first.0 > 1.0 { fusedWindow.removeFirst() }
        smooth = PhoneTracker.median(fusedWindow.map(\.1))
        updateGrid(t)

        // footfalls: the bounce in the vertical acceleration
        upFast += (1 - exp(-dt / 0.06)) * (up - upFast)
        upSlow += (1 - exp(-dt / 1.0)) * (up - upSlow)
        let v = upFast - upSlow
        if stepArmed && v > 0.07 && t - lastPeak >= 0.38 {
            stepArmed = false; lastPeak = t
            if let last = pending.last, t - last > 1.3 { pending = []; walking = false }
            pending.append(t)
            if walking { detected += 1; pending = [t] }
            else if pending.count >= 3 { walking = true; detected += pending.count; pending = [t] }
            reconcile(t)
        } else if v < 0 {
            stepArmed = true
        }
        if walking && t - lastPeak > 1.3 { walking = false; pending = [] }
    }

    private func pedometer(steps n: Int, distance: Double?) {
        guard running else { return }
        pedAlive = true
        pedSince = n
        if let d = distance, n >= 15, d > 0 { stepLength = max(0.5, min(0.95, d / Double(n))) }
        let t = Date().timeIntervalSince1970
        log.add("ped,\(f3(t)),\(n),\(f2(distance ?? 0))")
        reconcile(t)
    }

    private func barometer(_ metres: Double) {
        guard running else { return }
        if altitudeBase == nil { altitudeBase = metres }
        altitude = metres - (altitudeBase ?? metres)
    }

    /// One step count from three: the phone's footfalls (instant), the band's counter and Apple's
    /// pedometer (both late to start, both steady). Never behind the steady ones; never more than
    /// 16 ahead of them while one of them is alive.
    private func reconcile(_ t: Double) {
        let bandAlive = t - lastBandActivity < 3
        let reference = max(bandAlive ? bandSince : 0, pedSince)
        var target = max(detected, reference)
        if bandAlive || pedAlive { target = min(target, reference + 16) }
        if target > steps { advance(target - steps, t) }
    }

    // MARK: the band (50 motion samples a second, steps 10 a second)

    /// One motion sample from the band: acceleration in g, turning speed in degrees/second.
    func motion(t: Double, ax: Double, ay: Double, az: Double, gx: Double, gy: Double, gz: Double) {
        guard running else { return }
        let dt = lastMotion.map { max(0, min(0.2, t - $0)) } ?? 0
        lastMotion = t
        log.add("b,\(f3(t)),\(f3(ax)),\(f3(ay)),\(f3(az)),\(f2(gx)),\(f2(gy)),\(f2(gz))")
        let fusedMode = phoneActive
        let accel = (ax * ax + ay * ay + az * az).squareRoot()
        var g = gravity ?? [ax, ay, az]
        if gravity != nil { g = [g[0] + 0.05 * (ax - g[0]), g[1] + 0.05 * (ay - g[1]), g[2] + 0.05 * (az - g[2])] }
        gravity = g
        let norm = (g[0] * g[0] + g[1] * g[1] + g[2] * g[2]).squareRoot()
        if !fusedMode, accel < 0.3 || accel > 2.5 || norm < 0.3 || norm > 2.5 { uncertainty += max(4, 80 * dt) }
        guard norm >= 0.3 else { return }
        let yaw = (gx * g[0] + gy * g[1] + gz * g[2]) / norm

        // calibrate (and keep refining) only when truly still
        if (gx * gx + gy * gy + gz * gz).squareRoot() < 6 {
            quiet.append(yaw)
            if quiet.count > 15 { quiet.removeFirst() }
            if quiet.count == 15 {
                let m = PhoneTracker.median(quiet)
                if !bandCalibrated { bias = m; bandCalibrated = true } else { bias += 0.02 * (m - bias) }
            }
        } else {
            quiet = []
        }
        guard bandCalibrated else { return }

        // integrate (+ yaw = left = lower heading) and take the 2 s median (arm swing)
        unwrapped -= (yaw - bias) * dt
        window.append((t, unwrapped))
        while let first = window.first, t - first.0 > 2 { window.removeFirst() }
        bandSmooth = PhoneTracker.median(window.map(\.1))
        if fusedMode { return }             // the phone leads; the band's heading only bridges

        if dt > 0 { facingRaw += (1 - exp(-dt / 0.2)) * (unwrapped - facingRaw) }
        smooth = bandSmooth
        updateGrid(t)
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
        uncertainty += (phoneActive ? 0.12 : 0.4) * Double(n)      // the phone's gyro drifts far less
        if snapTurns && awaySince == nil {          // walking clearly off the grid, not mid-turn
            let off = abs(smooth - heading)
            if off > 30 { uncertainty += 0.25 * (off - 30) * Double(n) }
        }
        let d = Double(n) * stepLength
        let h = heading * .pi / 180
        x += d * sin(h)
        y += d * cos(h)
        steps += n
        log.add("s,\(f3(t)),\(steps),\(f2(x)),\(f2(y)),\(f2(heading)),\(detected),\(bandSince),\(pedSince),\(handling ? 1 : 0)")
        onPoint?(x, y, PhoneTracker.wrap(heading), steps, t)
    }

    /// One activity reading: the band's lifetime step total and still / walk / run.
    func activity(t: Double, total: Int, state: String) {
        guard running else { return }
        self.state = state
        lastBandActivity = t
        guard let last = lastSteps, calibrated else { lastSteps = total; return }
        let new = total - last
        lastSteps = total
        guard new > 0 else { return }
        log.add("a,\(f3(t)),\(total),\(state)")
        if phoneActive { bandSince += new; reconcile(t) }
        else if stepSource == "band" { advance(new, t) }
    }

    /// You are at a known spot: reset position and heading, clear the doubt (cancels drift).
    func reanchor(x: Double, y: Double, heading h: Double, t: Double) {
        self.x = x; self.y = y
        let w = PhoneTracker.wrap(h)
        heading = w; smooth = w; unwrapped = w; bandSmooth = w; facingRaw = w
        fused = w; phoneOffset = phoneHeading - w; fusedWindow = []; history = []; handling = false; stableSince = nil
        window = []; awaySince = nil; uncertainty = 0
        onPoint?(x, y, w, steps, t)
    }

    private func f2(_ v: Double) -> String { String(format: "%.2f", v) }
    private func f3(_ v: Double) -> String { String(format: "%.3f", v) }
}

/// The iPhone's motion sensors: gyro + accelerometer fusion (no magnetometer: steel indoors bends
/// it), Apple's pedometer, and the barometer. Everything is delivered on the main queue.
final class PhoneSensors {
    var onMotion: ((_ t: Double, _ stamp: Double, _ rate: Double, _ gravity: [Double], _ up: Double) -> Void)?
    var onPedometer: ((_ steps: Int, _ distance: Double?) -> Void)?
    var onAltitude: ((_ metres: Double) -> Void)?

    private let motion = CMMotionManager()
    private let pedometer = CMPedometer()
    private let altimeter = CMAltimeter()

    func start() {
        if motion.isDeviceMotionAvailable && !motion.isDeviceMotionActive {
            motion.deviceMotionUpdateInterval = 1.0 / 50
            motion.startDeviceMotionUpdates(using: .xArbitraryZVertical, to: .main) { [weak self] m, _ in
                guard let self, let m else { return }
                let g = m.gravity, w = m.rotationRate, a = m.userAcceleration
                // gravity points down: turning about "down" is clockwise seen from above
                let rate = (w.x * g.x + w.y * g.y + w.z * g.z) * 180 / .pi
                let up = -(a.x * g.x + a.y * g.y + a.z * g.z)
                self.onMotion?(Date().timeIntervalSince1970, m.timestamp, rate, [g.x, g.y, g.z], up)
            }
        }
        if CMAltimeter.isRelativeAltitudeAvailable() {
            altimeter.startRelativeAltitudeUpdates(to: .main) { [weak self] d, _ in
                if let d { self?.onAltitude?(d.relativeAltitude.doubleValue) }
            }
        }
    }

    func restartPedometer() {
        guard CMPedometer.isStepCountingAvailable() else { return }
        pedometer.stopUpdates()
        pedometer.startUpdates(from: Date()) { [weak self] data, _ in
            guard let data else { return }
            let n = data.numberOfSteps.intValue, d = data.distance?.doubleValue
            DispatchQueue.main.async { self?.onPedometer?(n, d) }
        }
    }
}

/// Every sensor reading and step of the current route, written to Documents/walk-latest.csv so a
/// walk can be pulled off the phone and replayed. p = phone, b = band motion, a = band steps,
/// ped = pedometer, s = a step on the map.
struct WalkLog {
    private var handle: FileHandle?
    private var buffer = ""

    mutating func open() {
        flush()
        try? handle?.close()
        guard let dir = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask).first else { return }
        let url = dir.appendingPathComponent("walk-latest.csv")
        FileManager.default.createFile(atPath: url.path, contents: nil)
        handle = try? FileHandle(forWritingTo: url)
        buffer = ""
    }

    mutating func add(_ line: String) {
        guard handle != nil else { return }
        buffer += line + "\n"
        if buffer.utf8.count > 16_000 { flush() }
    }

    mutating func flush() {
        guard let handle, !buffer.isEmpty else { return }
        try? handle.write(contentsOf: Data(buffer.utf8))
        buffer = ""
    }
}
