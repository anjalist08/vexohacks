import Foundation
import SwiftUI
import UIKit
import CoreMotion

struct TrailPoint { var x: Double; var y: Double; var jump: Bool }
struct Place: Identifiable, Equatable {
    let id: String
    var label: String
    var x: Double
    var y: Double
    var note: String?
    var floor: String?
}
struct DirectionStep: Identifiable { let id: Int; let turn: String; let steps: Int; let text: String }

/// One item in the Home screen's live activity feed: what you said, what Wayback did,
/// turn/guidance buzz cues, and occasional Vexo band alerts (disconnect, reconnect, low battery).
struct FeedItem: Identifiable, Equatable {
    enum Kind: String, Equatable { case heard, action, buzz, band }
    let id = UUID()
    let time: Date
    let kind: Kind
    let title: String
    let detail: String?
    let icon: String
    let tint: String
}

/// JSON numbers arrive as NSNumber; read them as Double or Int whatever their form.
private func num(_ v: Any?) -> Double? { (v as? NSNumber)?.doubleValue }
private func int(_ v: Any?) -> Int? { (v as? NSNumber)?.intValue }

/// Connects to the laptop app (python3 main.py --band --phone) and turns its guidance into
/// haptics and on-screen directions. The laptop does the band, tracking, routes and voice.
@MainActor
final class Guide: ObservableObject {
    enum Link: Equatable { case off, connecting, on, failed(String) }

    @Published var link: Link = .off
    @Published var big = "Not connected"
    @Published var sub = "Paste the phone link from the terminal, then Connect."
    @Published var arrowDegrees: Double = 0
    @Published var state = "idle"           // idle, on, wrong, lost, done
    @Published var voice = ""
    @Published var lastCue = ""
    @Published var buzzing = true
    @Published var bandStatus = ""          // the iPhone's own Bluetooth link to the band (bridge mode)

    // The route and places, as the laptop app records them (same feed as the trail page).
    @Published var trail: [TrailPoint] = []
    @Published var backTrail: [TrailPoint] = []
    @Published var places: [Place] = []
    @Published var directions: [DirectionStep] = []
    @Published var directionIndex = 0
    @Published var guiding = false
    @Published var guideTarget = ""
    @Published var waypoints: [CGPoint] = []
    @Published var position = CGPoint.zero
    @Published var steps = 0
    @Published var facing: Double = 0       // live heading, degrees clockwise from the route's start direction
    @Published var recording = false
    @Published var calibrated = false
    @Published var uncertain = false
    @Published var activity = "–"
    @Published var gyroBias: Double = 0
    @Published var stepLength: Double = 0.7
    @Published var mode = ""                // LIVE, REPLAY, SIMULATION
    @Published var bandLinkStatus = "not connected"
    @Published var bandName = BandConfig.name
    @Published var bandVia = ""
    @Published var battery: Int?
    @Published var batteryState = ""
    @Published var batteryVolts: Double?
    @Published var chipTemp: Double?
    @Published var ledState = "idle"
    @Published var lastReply = ""
    @Published var bridgeWanted = false     // the laptop runs --bridge and wants this phone to carry the band
    @Published var level = 0                // floors up or down since the route started (barometer)
    @Published var trackSource = ""         // which sensors lead the tracking right now
    @Published var phoneOnly = false        // iPhone only: no laptop; the phone tracks, guides, listens and speaks
    @Published var feed: [FeedItem] = []    // newest-first live log shown on the Home (Guide) tab

    private var lastLoggedLinkState = "not connected"
    private var lastLoggedCue: (cue: String, at: Date)?
    private var lowBatteryLogged = false
    private var hadConnectedOnce = false

    lazy var brain: PhoneBrain = { let b = PhoneBrain(); b.guide = self; return b }()
    lazy var voiceEngine: PhoneVoice = PhoneVoice(guide: self)

    private var band: BandLink?             // made only when the laptop asks the phone to carry the band

    let haptics = Haptics()
    private let phoneMotion = PhoneMotion()   // the iPhone's own heading + pedometer, for sensor fusion
    private var task: URLSessionWebSocketTask?
    private var wanted: URL?

    /// "http://192.168.1.23:8000/web/phone.html?ws_port=8765&token=abc" -> ws://192.168.1.23:8765/?token=abc
    static func webSocketURL(fromPhoneLink text: String) -> URL? {
        guard let comps = URLComponents(string: text.trimmingCharacters(in: .whitespacesAndNewlines)),
              let host = comps.host else { return nil }
        let items = comps.queryItems ?? []
        let port = Int(items.first(where: { $0.name == "ws_port" })?.value ?? "") ?? 8765
        var ws = URLComponents()
        ws.scheme = "ws"
        ws.host = host
        ws.port = port
        ws.path = "/"
        if let token = items.first(where: { $0.name == "token" })?.value, !token.isEmpty {
            ws.queryItems = [URLQueryItem(name: "token", value: token)]
        }
        return ws.url
    }

    func connect(phoneLink: String) {
        guard let url = Guide.webSocketURL(fromPhoneLink: phoneLink) else {
            link = .failed("That doesn't look like the phone link.")
            return
        }
        wanted = url
        open(url)
        UIApplication.shared.isIdleTimerDisabled = true      // haptics only play while the app is on screen
        phoneMotion.onMessage = { [weak self] msg in Task { @MainActor in self?.send(msg) } }
        phoneMotion.start()
    }

    /// Run everything on this iPhone: connect the band over Bluetooth, track, guide, listen and speak here.
    func startPhoneOnly() {
        phoneOnly = true
        _ = brain
        link = .on
        big = band?.verified == true ? "Ready" : "Connect \(BandConfig.name)"
        sub = band?.verified == true
            ? "Double-tap the band and say \"start route\"."
            : "Double-tap \(BandConfig.name) so its light blinks blue."
        UIApplication.shared.isIdleTimerDisabled = true      // haptics only play while the app is on screen
        carryBand()
    }

    func runOnBand(_ cmd: [String: Any]) { band?.run(command: cmd) }

    /// Flash Vexo-HACK-80 white so the user can visually confirm the iPhone Bluetooth link.
    func flashBand() {
        guard band?.verified == true else { return }
        if phoneOnly {
            brain.led(recording ? "route_started" : "connected_flash")
        } else {
            runOnBand(["op": "setLed", "args": ["color": "#ffffff", "brightness": 1.0, "pattern": "flash", "period": 400]])
        }
    }

    /// Clear any cached CoreBluetooth peripheral identifier and scan fresh for Vexo-HACK-80.
    func resetBandBluetooth() {
        band?.stop()
        band = nil
        bandName = BandConfig.name
        bandLinkStatus = "not connected"
        BandLink.forgetRemembered()
        if link != .on { startPhoneOnly(); return }
        carryBand()
    }

    func disconnect() {
        phoneMotion.stop()
        phoneOnly = false
        band?.stop()
        band = nil
        bandStatus = ""
        bridgeWanted = false
        wanted = nil
        task?.cancel(with: .goingAway, reason: nil)
        task = nil
        link = .off
        big = "Not connected"
        state = "idle"
        UIApplication.shared.isIdleTimerDisabled = false
    }

    private func open(_ url: URL) {
        task?.cancel()
        link = .connecting
        let t = URLSession.shared.webSocketTask(with: url)
        task = t
        t.resume()
        receive(on: t)
    }

    private func receive(on t: URLSessionWebSocketTask) {
        t.receive { [weak self] result in
            Task { @MainActor in
                guard let self, self.task === t else { return }
                switch result {
                case .success(let message):
                    if self.link != .on { self.link = .on }
                    if case .string(let text) = message { self.handle(text) }
                    self.receive(on: t)
                case .failure:
                    self.link = .failed("Lost the laptop. Retrying…")
                    if let url = self.wanted {
                        try? await Task.sleep(nanoseconds: 1_500_000_000)
                        if self.wanted == url { self.open(url) }
                    }
                }
            }
        }
    }

    func talk() {
        if phoneOnly { voiceEngine.doubleTap(); return }
        task?.send(.string(#"{"type":"talk"}"#)) { _ in }
    }

    /// Send one JSON message to the laptop app.
    func send(_ message: [String: Any]) {
        guard let data = try? JSONSerialization.data(withJSONObject: message),
              let text = String(data: data, encoding: .utf8) else { return }
        task?.send(.string(text)) { _ in }
    }

    /// A typed (or tapped) command, understood by the laptop's Gemini like speech.
    func command(_ text: String) {
        let t = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !t.isEmpty else { return }
        logHeard(t, viaSpeech: false)
        if phoneOnly {
            lastReply = "You typed: \(t)"
            Task { await voiceEngine.understand(t) }
            return
        }
        send(["type": "command", "text": t])
        lastReply = "Sent: \(t)"
    }

    // MARK: - Home screen activity feed helpers

    func clearFeed() { feed.removeAll() }

    private func pushFeed(_ item: FeedItem) {
        // Skip exact back-to-back duplicate titles within 1.5 s.
        if let top = feed.first, top.kind == item.kind, top.title == item.title,
           item.time.timeIntervalSince(top.time) < 1.5 {
            return
        }
        feed.insert(item, at: 0)
        if feed.count > 50 { feed.removeLast(feed.count - 50) }
    }

    func logHeard(_ words: String, viaSpeech: Bool = true) {
        let clean = words.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !clean.isEmpty else { return }
        pushFeed(FeedItem(
            time: Date(),
            kind: .heard,
            title: "You: \"\(clean)\"",
            detail: viaSpeech ? "Heard from wrist mic" : "Tapped / typed command",
            icon: viaSpeech ? "waveform.and.mic" : "hand.tap.fill",
            tint: "blue"
        ))
    }

    func logAction(_ title: String, detail: String? = nil, icon: String = "sparkles", tint: String = "green") {
        pushFeed(FeedItem(time: Date(), kind: .action, title: title, detail: detail, icon: icon, tint: tint))
    }

    func logBuzz(_ cue: String) {
        // Ignore the quiet 4 s keep-alive tick so the feed stays readable.
        guard cue != "tick" else { return }
        let now = Date()
        if let prev = lastLoggedCue, prev.cue == cue, now.timeIntervalSince(prev.at) < 8.0 {
            return
        }
        lastLoggedCue = (cue, now)
        let labels: [String: (String, String)] = [
            "wrong_left": ("Turn left (buzz ••)", "Facing right of route"),
            "wrong_right": ("Turn right (buzz •••)", "Facing left of route"),
            "on_track": ("Facing the right way (buzz ━━━)", "Locked onto current leg"),
            "turn_soon": ("Turn coming up (buzz ····)", "Approaching corner"),
            "turn_left": ("Turn left now (buzz ━•)", "Corner reached"),
            "turn_right": ("Turn right now (buzz ━••)", "Corner reached"),
            "turn_around": ("Turn around now (buzz ━━)", "Reverse direction"),
            "arrived": ("Arrived at destination (buzz ━━━)", "Guidance complete"),
            "lost": ("Position uncertain (buzz •••••)", "Say \"I'm at the …\" to re-anchor"),
        ]
        guard let info = labels[cue] else { return }
        pushFeed(FeedItem(
            time: now,
            kind: .buzz,
            title: info.0,
            detail: info.1,
            icon: "iphone.radiowaves.left.and.right",
            tint: cue == "arrived" ? "purple" : cue == "on_track" ? "green" : cue == "lost" ? "red" : "orange"
        ))
    }

    func noteBandLinkTransition(_ rawStatus: String) {
        let s = rawStatus.lowercased()
        guard s != lastLoggedLinkState else { return }
        let prev = lastLoggedLinkState
        lastLoggedLinkState = s
        if s == "connected" || s == "reconnected" {
            let re = (s == "reconnected") || (hadConnectedOnce && (prev == "reconnecting" || prev == "lost" || prev == "disconnected" || prev == "not connected"))
            hadConnectedOnce = true
            pushFeed(FeedItem(
                time: Date(),
                kind: .band,
                title: re ? "\(bandName) reconnected" : "\(bandName) connected",
                detail: bandVia.isEmpty ? nil : bandVia,
                icon: "checkmark.circle.fill",
                tint: "green"
            ))
        } else if s == "reconnecting" || s == "lost" || s == "disconnected" {
            guard hadConnectedOnce else { return }
            pushFeed(FeedItem(
                time: Date(),
                kind: .band,
                title: s == "reconnecting" ? "\(bandName) disconnected — reconnecting…" : "\(bandName) disconnected",
                detail: "Double-tap \(bandName) if its blue blink stopped",
                icon: "antenna.radiowaves.left.and.right.slash",
                tint: "orange"
            ))
        }
    }

    func noteBattery(percent: Int?, state: String) {
        guard let pct = percent else { return }
        if pct > 20 || state == "charging" {
            lowBatteryLogged = false
            return
        }
        if pct <= 15 && !lowBatteryLogged {
            lowBatteryLogged = true
            pushFeed(FeedItem(
                time: Date(),
                kind: .band,
                title: "\(bandName) low battery (\(pct)%)",
                detail: "Plug into USB-C power soon",
                icon: "battery.25",
                tint: "red"
            ))
        }
    }

    /// The Band tab's button: connect the iPhone to the band over Bluetooth now.
    /// If neither laptop nor iPhone-only mode is active yet, enter iPhone-only mode automatically.
    func connectBandFromPhone() {
        if link != .on {
            startPhoneOnly()
            return
        }
        carryBand()
    }

    func disconnectBandFromPhone() {
        band?.stop()
        band = nil
        bandLinkStatus = "not connected"
        bandStatus = "Disconnected from the band"
        noteBandLinkTransition("disconnected")
    }

    var carryingBand: Bool { band != nil }
    var bandConnectedOnPhone: Bool { band?.verified == true }

    /// The laptop runs `main.py --bridge` (or iPhone-only mode): this phone connects to the band and carries its data.
    private func carryBand() {
        bandName = BandConfig.name
        if let existing = band {
            if existing.verified && !phoneOnly {
                send(["type": "band_status", "status": "connected", "name": BandConfig.name,
                      "transport": "iPhone Bluetooth"])
            }
            return
        }
        let link = BandLink()
        link.onStatus = { [weak self] text in
            print("[band] \(text)")
            Task { @MainActor in self?.bandStatus = text }
        }
        link.onMessage = { [weak self] msg in
            Task { @MainActor in
                guard let self else { return }
                if msg["type"] as? String == "band_status", let status = msg["status"] as? String {
                    self.bandLinkStatus = status
                    self.bandVia = "iPhone Bluetooth"
                    self.noteBandLinkTransition(status)
                    if status == "connected" && self.phoneOnly && self.state == "idle" {
                        self.big = "Ready"
                        self.sub = "Double-tap the band and say \"start route\"."
                    }
                }
                if self.phoneOnly { self.brain.band(msg) } else { self.send(msg) }   // phone brain, or the laptop
            }
        }
        band = link
        link.start()
    }

    func tryCue(_ cue: String) {
        haptics.play(cue)
        lastCue = cue
        logBuzz(cue)
    }

    // MARK: messages from the laptop app

    private func handle(_ text: String) {
        guard let data = text.data(using: .utf8),
              let m = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let type = m["type"] as? String else { return }
        switch type {
        case "haptic":
            if let cue = m["cue"] as? String {
                lastCue = cue
                if buzzing { haptics.play(cue) }
                logBuzz(cue)
            }
        case "haptic_hint":
            showHint(m)
        case "voice":
            let s = m["state"] as? String ?? ""
            switch s {
            case "listening": voice = "Listening… speak now"
            case "heard":
                let heardText = m["text"] as? String ?? ""
                voice = "Heard: " + heardText
                logHeard(heardText, viaSpeech: true)
            case "thinking": voice = "Understanding…"
            case "done":
                let spoken = m["say"] as? String ?? ""
                voice = spoken
                if !spoken.isEmpty {
                    logAction("Wayback: \"\(spoken)\"", icon: "speaker.wave.2.fill", tint: "cyan")
                }
            default: voice = m["text"] as? String ?? ""
            }
        case "say":
            let spoken = m["text"] as? String ?? ""
            voice = spoken
            if !spoken.isEmpty {
                logAction("Wayback: \"\(spoken)\"", icon: "speaker.wave.2.fill", tint: "cyan")
            }
        case "band_number":
            if let n = int(m["band"]), n == BandConfig.number {   // only our band
                bridgeWanted = true
                carryBand()
            } else {
                bridgeWanted = false
            }
        case "band_cmd":
            band?.run(command: m)
        case "mode":
            mode = m["mode"] as? String ?? ""
        case "link":
            let s = m["status"] as? String ?? "not connected"
            bandLinkStatus = s
            noteBandLinkTransition(s)
        case "led":
            ledState = m["state"] as? String ?? "idle"
        case "reset":
            trail = []; backTrail = []; places = []; directions = []; guiding = false; waypoints = []
            logAction("Started route", detail: "Stand still briefly to calibrate gyro", icon: "play.circle.fill", tint: "green")
        case "point":
            let p = TrailPoint(x: num(m["x_m"]) ?? 0, y: num(m["y_m"]) ?? 0, jump: m["jump"] as? Bool ?? false)
            if guiding { backTrail.append(p) } else { trail.append(p) }
            position = CGPoint(x: p.x, y: p.y)
            steps = int(m["steps"]) ?? steps
            if p.jump {
                logAction("Re-anchored position", detail: String(format: "Snapped to (%.1f, %.1f m)", p.x, p.y), icon: "scope", tint: "blue")
            }
        case "landmark":
            let place = Place(id: m["id"] as? String ?? UUID().uuidString, label: m["label"] as? String ?? "place",
                              x: num(m["x_m"]) ?? position.x, y: num(m["y_m"]) ?? position.y,
                              note: m["note"] as? String, floor: m["floor"] as? String)
            let isNew = !places.contains(where: { $0.id == place.id })
            if let i = places.firstIndex(where: { $0.id == place.id }) { places[i] = place } else { places.append(place) }
            if isNew {
                logAction("Added landmark: \(place.label.capitalized)", detail: place.note, icon: "mappin.circle.fill", tint: "purple")
            }
        case "guidance":
            let wasGuiding = guiding
            let prevIdx = directionIndex
            let list = m["instructions"] as? [[String: Any]] ?? []
            directions = list.enumerated().map { i, d in
                DirectionStep(id: i, turn: d["turn"] as? String ?? "", steps: int(d["steps"]) ?? 0,
                              text: d["text"] as? String ?? "")
            }
            directionIndex = int(m["current_index"]) ?? 0
            guiding = m["active"] as? Bool ?? false
            guideTarget = m["target_name"] as? String ?? guideTarget
            waypoints = (m["waypoints"] as? [[Any]] ?? []).compactMap { w in
                guard w.count >= 2, let x = num(w[0]), let y = num(w[1]) else { return nil }
                return CGPoint(x: x, y: y)
            }
            if guiding && !wasGuiding {
                logAction("Guiding to \(guideTarget)", detail: directions.first?.text, icon: "figure.walk.circle.fill", tint: "cyan")
            } else if guiding && directionIndex != prevIdx, directionIndex < directions.count {
                logAction(directions[directionIndex].text, detail: "Step \(directionIndex + 1) of \(directions.count)", icon: "arrow.triangle.turn.up.right.circle.fill", tint: "cyan")
            }
            if !guiding { backTrail = [] }
        case "tracker":
            let wasRecording = recording
            recording = m["running"] as? Bool ?? recording
            calibrated = m["calibrated"] as? Bool ?? calibrated
            facing = num(m["live_heading_deg"]) ?? facing
            uncertain = m["uncertain"] as? Bool ?? false
            activity = m["state"] as? String ?? activity
            gyroBias = num(m["bias_dps"]) ?? gyroBias
            steps = int(m["steps"]) ?? steps
            if wasRecording && !recording {
                logAction("Ended route", detail: "\(steps) steps recorded", icon: "stop.circle.fill", tint: "gray")
            }
        case "band_metric":
            switch m["kind"] as? String {
            case "info":
                bandName = m["name"] as? String ?? bandName
                bandVia = m["transport"] as? String ?? bandVia
            case "battery":
                battery = int(m["percent"])
                batteryState = m["state"] as? String ?? ""
                batteryVolts = num(m["millivolts"]).map { $0 / 1000 }
                noteBattery(percent: battery, state: batteryState)
            case "temperature":
                chipTemp = num(m["celsius"])
            default:
                break
            }
        default:
            break
        }
    }

    func showHint(_ m: [String: Any]) {
        let target = (m["target"] as? String).map { "the " + $0 } ?? "the place"
        if m["arrived"] as? Bool == true {
            state = "done"; big = "Arrived"; sub = "You reached \(target)."; return
        }
        guard m["active"] as? Bool == true else {
            state = "idle"; big = "Waiting for a route"; sub = "Say \"take me to the kitchen\"."; return
        }
        if m["lost"] as? Bool == true {
            state = "lost"; big = "Not sure where you are"; sub = "Say \"I'm at the …\" to re-anchor."; return
        }
        let err = (m["error_deg"] as? Double) ?? 0
        // keep the angle continuous so +180 / -180 does not spin the arrow
        var diff = (err - arrowDegrees).truncatingRemainder(dividingBy: 360)
        if diff > 180 { diff -= 360 } else if diff < -180 { diff += 360 }
        arrowDegrees += diff
        let hintState = m["state"] as? String ?? ""
        let stepsLeft = m["steps_left"] as? Int
        if hintState == "wrong_left" || hintState == "wrong_right" {
            state = "wrong"
            big = abs(err) >= 150 ? "Turn around" : (hintState == "wrong_left" ? "Turn left" : "Turn right")
            sub = "\(Int(abs(err).rounded()))° off, to \(target)"
        } else {
            state = "on"
            if hintState == "turn_soon", let turn = m["next_turn"] as? String, let n = stepsLeft {
                big = "Turn \(turn) in \(n) step\(n == 1 ? "" : "s")"
            } else {
                big = "Straight ahead"
            }
            sub = stepsLeft.map { "\($0) steps on this stretch, to \(target)" } ?? "to \(target)"
        }
    }
}


/// The iPhone's own motion, sent to the laptop 10 times a second as {"type": "phone_motion"} for
/// sensor fusion (tracker/wrist.py, WristTracker.on_phone). In a pocket the phone turns with the
/// body and does not swing like a wrist, so the laptop uses its heading for the walking direction,
/// and Apple's pedometer (calibrated to the walker) for the stride.
/// Heading uses gyro fusion without the magnetometer (.xArbitraryCorrectedZVertical), so steel
/// and elevators indoors cannot swing it; the laptop makes it relative to the start of the route.
final class PhoneMotion {
    var onMessage: (([String: Any]) -> Void)?
    private let motion = CMMotionManager()
    private let pedometer = CMPedometer()
    private let queue = OperationQueue()
    private let lock = NSLock()
    private var lastYaw: Double?
    private var heading = 0.0          // degrees clockwise, unwrapped (keeps counting past 360)
    private var steps: Int?
    private var distance: Double?
    private var timer: Timer?

    func start() {
        stop()
        queue.maxConcurrentOperationCount = 1
        if motion.isDeviceMotionAvailable {
            motion.deviceMotionUpdateInterval = 1.0 / 30
            motion.startDeviceMotionUpdates(using: .xArbitraryCorrectedZVertical, to: queue) { [weak self] m, _ in
                guard let self, let m else { return }
                let yaw = m.attitude.yaw * 180 / .pi          // counter-clockwise about the vertical
                self.lock.lock()
                if let last = self.lastYaw {
                    var d = yaw - last
                    if d > 180 { d -= 360 } else if d < -180 { d += 360 }
                    self.heading -= d                          // clockwise, like the laptop's map
                }
                self.lastYaw = yaw
                self.lock.unlock()
            }
        }
        if CMPedometer.isStepCountingAvailable() {
            pedometer.startUpdates(from: Date()) { [weak self] data, _ in
                guard let self, let data else { return }
                self.lock.lock()
                self.steps = data.numberOfSteps.intValue
                self.distance = data.distance?.doubleValue
                self.lock.unlock()
            }
        }
        timer = Timer.scheduledTimer(withTimeInterval: 0.1, repeats: true) { [weak self] _ in self?.emit() }
    }

    func stop() {
        timer?.invalidate()
        timer = nil
        motion.stopDeviceMotionUpdates()
        pedometer.stopUpdates()
        lock.lock()
        lastYaw = nil
        heading = 0
        steps = nil
        distance = nil
        lock.unlock()
    }

    private func emit() {
        lock.lock()
        defer { lock.unlock() }
        guard lastYaw != nil else { return }
        var msg: [String: Any] = ["type": "phone_motion", "t": Date().timeIntervalSince1970,
                                  "heading_deg": (heading * 10).rounded() / 10]
        if let steps, let distance {
            msg["steps"] = steps
            msg["distance_m"] = (distance * 100).rounded() / 100
        }
        onMessage?(msg)
    }
}
