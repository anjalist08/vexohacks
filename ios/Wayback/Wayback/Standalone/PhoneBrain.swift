import Foundation

/// Everything the laptop app did, on the phone: the route and places (a route graph),
/// guidance that follows you, the buzz coach, the band's light, and commands.
/// Code computes every position, distance and turn; the model only picks the action.
@MainActor
final class PhoneBrain {
    weak var guide: Guide?
    let tracker = PhoneTracker()

    // route: points, re-anchor jumps (index -> same place as index), places
    private var points: [TrailPoint] = []
    private var jumps: [Int: Int] = [:]
    private var places: [Place] = []
    private var placeIndex: [String: Int] = [:]
    private var routeActive = false
    private var nextPlace = 1
    private var jumpNext: Int?               // the next tracker point is a re-anchor to this index
    private var nav: Navigation?
    private var coach = Coach()
    private var timer: Timer?
    private var lastTime = Date().timeIntervalSince1970

    init() {
        tracker.onPoint = { [weak self] x, y, h, s, t in
            MainActor.assumeIsolated { self?.onPoint(x: x, y: y, heading: h, steps: s, t: t) }
        }
        timer = Timer.scheduledTimer(withTimeInterval: 0.2, repeats: true) { [weak self] _ in
            MainActor.assumeIsolated { self?.tick() }
        }
    }

    // MARK: band data in (the same messages BandLink relays)

    func band(_ m: [String: Any]) {
        guard m["type"] as? String == "band_event" else {
            if m["type"] as? String == "band_status" { bandStatus(m) }
            return
        }
        let n = { (k: String) in (m[k] as? NSNumber)?.doubleValue ?? 0 }
        let t = (m["time"] as? NSNumber)?.doubleValue ?? Date().timeIntervalSince1970
        lastTime = t
        switch m["kind"] as? String {
        case "motion":
            tracker.motion(t: t, ax: n("ax"), ay: n("ay"), az: n("az"), gx: n("gx"), gy: n("gy"), gz: n("gz"))
        case "activity":
            tracker.activity(t: t, total: Int(n("steps")), state: m["state"] as? String ?? "still")
            guide?.activity = m["state"] as? String ?? "–"
        case "event":
            if m["event"] as? String == "double-tap" { guide?.voiceEngine.doubleTap() }
        case "battery":
            guide?.battery = Int(n("percent"))
            guide?.batteryState = m["state"] as? String ?? ""
            guide?.batteryVolts = n("millivolts") / 1000
        case "temperature":
            guide?.chipTemp = n("celsius")
        case "audio":
            guide?.voiceEngine.audio(m)
        default:
            break
        }
    }

    private func bandStatus(_ m: [String: Any]) {
        let status = m["status"] as? String ?? ""
        guide?.bandLinkStatus = status
        if status == "connected" {
            guide?.bandVia = "iPhone Bluetooth"
            guide?.bandName = m["name"] as? String ?? BandConfig.name
            // what the laptop used to turn on: 50 motion samples/s, steps 10/s, taps, battery, temperature
            bandCommand(["op": "configure", "args": ["motion": 50, "activity": "fastest", "events": true,
                                                     "battery": true, "temperature": 5]])
            // Flash white on connect (like the Vexo dashboard's identify), then return to route state.
            led(routeActive ? "recording" : "connected_flash")
        }
    }

    func bandCommand(_ cmd: [String: Any]) { guide?.runOnBand(cmd) }

    // MARK: the band's light (voice/led_states.py)

    private var ledTimer: Timer?
    func led(_ state: String, period: Int? = nil) {
        ledTimer?.invalidate()
        guide?.ledState = state
        let cues: [String: (String, String, Int, String?)] = [
            "idle": ("#000000", "off", 1000, nil),
            "connected_flash": ("#ffffff", "flash", 400, "idle"),
            "route_started": ("#00ff00", "blink", 400, "recording"),
            "recording": ("#ffb000", "breathe", 2000, nil),
            "landmark_saved": ("#a020f0", "solid", 1000, "recording"),
            "navigating": ("#ffffff", "breathe", 2000, nil),
            "turn_now": ("#ffffff", "blink", 500, nil),
            "arrived": ("#00ff00", "solid", 1000, "arrived_party"),
            "arrived_party": ("#ffffff", "rainbow", 2000, nil),
            "uncertain": ("#ff0000", "blink", 500, nil),
        ]
        guard let c = cues[state] else { return }
        if c.1 == "off" { bandCommand(["op": "ledOff", "args": [:]]) }
        else { bandCommand(["op": "setLed", "args": ["color": c.0, "brightness": 1.0, "pattern": c.1, "period": period ?? c.2]]) }
        if let then = c.3 {
            ledTimer = Timer.scheduledTimer(withTimeInterval: 1.5, repeats: false) { [weak self] _ in
                MainActor.assumeIsolated { self?.led(then) }
            }
        }
    }

    // MARK: speaking and showing

    private func say(_ text: String, led state: String? = nil) {
        guide?.voice = text
        guide?.voiceEngine.speak(text)
        if let state { led(state) }
    }

    private func publish() {
        guard let g = guide else { return }
        var trail: [TrailPoint] = []
        for (i, p) in points.enumerated() { trail.append(TrailPoint(x: p.x, y: p.y, jump: jumps[i] != nil)) }
        g.trail = trail
        g.places = places
        g.recording = tracker.running
    }

    // MARK: points from the tracker

    private func onPoint(x: Double, y: Double, heading: Double, steps: Int, t: Double) {
        guide?.position = CGPoint(x: x, y: y)
        guide?.steps = steps
        if let n = nav, n.active {
            guide?.backTrail.append(TrailPoint(x: x, y: y, jump: false))
            follow(n, x: x, y: y)
            return
        }
        guard routeActive else { return }
        let jump = jumpNext
        jumpNext = nil
        if let j = jump { jumps[points.count] = j }
        points.append(TrailPoint(x: x, y: y, jump: jump != nil))
        publish()
    }

    private func tick() {
        guard let g = guide else { return }
        g.facing = tracker.facing
        g.calibrated = tracker.calibrated
        g.recording = tracker.running
        g.gyroBias = tracker.bias
        g.uncertain = tracker.uncertain
        let out = coach.update(nav: nav, facing: tracker.facing, x: tracker.x, y: tracker.y,
                               stepLength: tracker.stepLength, uncertain: tracker.uncertain)
        g.showHint(out.hint)
        if let cue = out.cue {
            g.lastCue = cue
            if g.buzzing { g.haptics.play(cue) }
        }
    }

    // MARK: commands (from voice, buttons or typing)

    func command(_ text: String) {
        run(PhoneCommands.parse(text, places: places))
    }

    func run(_ action: PhoneCommands.Action) {
        let t = lastTime
        switch action {
        case .startRoute:
            points = []; jumps = [:]; places = []; placeIndex = [:]; nextPlace = 1; nav = nil
            routeActive = true
            guide?.backTrail = []; guide?.directions = []; guide?.guiding = false; guide?.waypoints = []
            tracker.start(at: t)
            publish()
            say("Route started. Stand still for a moment.", led: "route_started")
        case .stopRoute:
            routeActive = false; nav = nil; tracker.stop(); guide?.guiding = false
            publish()
            say("Route saved.", led: "idle")
        case .remember(let label, let note):
            guard routeActive, !points.isEmpty else { say("Start a route first.", led: "uncertain"); return }
            let name = label.isEmpty ? "spot \(places.count + 1)" : label
            let p = points[points.count - 1]
            let id = "lm\(nextPlace)"; nextPlace += 1
            places.append(Place(id: id, label: name, x: p.x, y: p.y, note: note, floor: nil))
            placeIndex[id] = points.count - 1
            publish()
            say("Saved: \(name).", led: "landmark_saved")
        case .navigate(let target):
            navigate(to: target)
        case .reanchor(let target):
            guard let id = placeId(for: target), let i = placeIndex[id] else { say("I don't know that place.", led: "uncertain"); return }
            nav = nil; guide?.guiding = false
            jumpNext = i
            tracker.reanchor(x: points[i].x, y: points[i].y, heading: tracker.heading, t: t)
            say("Got it, you're at the \(label(of: id)).", led: "recording")
        case .find(let query):
            guard let id = placeId(for: query) else { say("I don't have a saved place like that."); return }
            let steps = Int((distanceBack(to: placeIndex[id] ?? 0) / tracker.stepLength).rounded())
            say("The \(label(of: id)) is about \(steps) steps away along your route.")
        case .ask(let q):
            say(q)
        }
    }

    private func label(of id: String) -> String { places.first { $0.id == id }?.label ?? "place" }

    private func placeId(for target: String) -> String? {
        if places.contains(where: { $0.id == target }) { return target }
        let words = Set(PhoneCommands.words(target))
        return places.max { a, b in
            Set(PhoneCommands.words(a.label)).intersection(words).count < Set(PhoneCommands.words(b.label)).intersection(words).count
        }.flatMap { Set(PhoneCommands.words($0.label)).intersection(words).isEmpty ? nil : $0.id }
    }

    // MARK: routing on the route graph

    /// Shortest path of point indices through walked steps; a re-anchor jump links two points
    /// that are the same place (length 0) and is never walked.
    private func path(from start: Int, to goal: Int) -> [Int]? {
        let n = points.count
        guard start < n, goal < n else { return nil }
        var adj = Array(repeating: [(Int, Double)](), count: n)
        for i in 1..<max(n, 1) where jumps[i] == nil {
            let d = hypot(points[i].x - points[i - 1].x, points[i].y - points[i - 1].y)
            adj[i - 1].append((i, d)); adj[i].append((i - 1, d))
        }
        for (j, k) in jumps where k < n { adj[j].append((k, 0)); adj[k].append((j, 0)) }
        var best = Array(repeating: Double.infinity, count: n), prev = Array(repeating: -1, count: n)
        var done = Array(repeating: false, count: n)
        best[start] = 0
        for _ in 0..<n {
            var u = -1
            for i in 0..<n where !done[i] && best[i] < .infinity && (u < 0 || best[i] < best[u]) { u = i }
            if u < 0 { break }
            if u == goal { break }
            done[u] = true
            for (v, w) in adj[u] where best[u] + w < best[v] { best[v] = best[u] + w; prev[v] = u }
        }
        guard best[goal] < .infinity else { return nil }
        var out = [goal]
        while out.last! != start { out.append(prev[out.last!]) }
        return out.reversed()
    }

    private func distanceBack(to index: Int) -> Double {
        guard let p = path(from: points.count - 1, to: index) else { return 0 }
        return zip(p, p.dropFirst()).reduce(0) { $0 + hypot(points[$1.1].x - points[$1.0].x, points[$1.1].y - points[$1.0].y) }
    }

    private func navigate(to target: String) {
        guard points.count > 1 else { say("There is no recorded route to follow yet.", led: "uncertain"); return }
        let index: Int, name: String
        if ["start", "the start", "beginning"].contains(target.lowercased()) && placeId(for: target) == nil {
            index = 0; name = "start"
        } else if let id = placeId(for: target), let i = placeIndex[id] {
            index = i; name = label(of: id)
        } else {
            say("I don't know that place. Which one did you mean?", led: "uncertain"); return
        }
        guard let order = path(from: points.count - 1, to: index) else { say("I can't find a path you walked there.", led: "uncertain"); return }
        let route = order.map { points[$0] }
        guard let n = Navigation(route: route, target: name, targetIndex: index, facing: tracker.heading,
                                 stepLength: tracker.stepLength) else {
            say("You're already at the \(name).", led: "arrived"); return
        }
        nav = n
        if !tracker.running { tracker.resume() }
        guide?.backTrail = []
        guide?.guiding = true
        guide?.guideTarget = name
        guide?.waypoints = n.corners.map { CGPoint(x: $0.0, y: $0.1) }
        guide?.directions = n.steps.enumerated().map { DirectionStep(id: $0.offset, turn: $0.element.turn, steps: $0.element.count, text: $0.element.text) }
        guide?.directionIndex = 0
        let texts = n.steps.map(\.text)
        say(texts.count == 1 ? texts[0] : ([texts[0]] + texts.dropFirst().map { "then " + $0.prefix(1).lowercased() + $0.dropFirst() }).joined(separator: " "),
            led: "navigating")
    }

    private func follow(_ n: Navigation, x: Double, y: Double) {
        for event in n.update(x: x, y: y) {
            switch event {
            case .say(let text, let state, let period):
                guide?.voice = text
                if !text.isEmpty { guide?.voiceEngine.speak(text) }
                if let state { led(state, period: period) }
            case .arrived(let text):
                guide?.voiceEngine.speak(text); guide?.voice = text
                led("arrived")
                guide?.guiding = false
                // reset to the destination's recorded spot (cancels drift) and keep recording from there
                let p = points[n.targetIndex]
                jumpNext = n.targetIndex
                tracker.reanchor(x: p.x, y: p.y, heading: tracker.heading, t: lastTime)
            }
        }
        guide?.directionIndex = n.segment
    }
}

// MARK: - Navigation: follow the walker along the planned legs (store/navigator.py)

final class Navigation {
    struct Step { let turn: String; let count: Int; let text: String }
    enum Event { case say(String, String?, Int?), arrived(String) }

    let target: String
    let targetIndex: Int
    let stepLength: Double
    private(set) var corners: [(Double, Double)] = []
    private(set) var steps: [Step] = []
    private(set) var headings: [Double] = []
    private var cum: [Double] = [0]
    private(set) var segment = 0
    private(set) var active = true
    private var progress = 0.0, offset = 0.0, offCount = 0
    private var warned = Set<Int>(), turned = Set<Int>(), lost = false

    var total: Double { cum.last ?? 0 }

    init?(route: [TrailPoint], target: String, targetIndex: Int, facing: Double, stepLength: Double) {
        self.target = target; self.targetIndex = targetIndex; self.stepLength = stepLength
        // merge the walked points into straight legs (within 30°), dropping legs under 0.5 m
        var legs: [(h: Double, dx: Double, dy: Double, sx: Double, sy: Double)] = []
        for (a, b) in zip(route, route.dropFirst()) {
            let dx = b.x - a.x, dy = b.y - a.y
            guard hypot(dx, dy) > 1e-6 else { continue }
            let h = atan2(dx, dy) * 180 / .pi
            if var last = legs.last, abs(PhoneTracker.wrap(h - last.h)) <= 30 {
                last.dx += dx; last.dy += dy; last.h = atan2(last.dx, last.dy) * 180 / .pi
                legs[legs.count - 1] = last
            } else {
                legs.append((h, dx, dy, a.x, a.y))
            }
        }
        legs = legs.filter { hypot($0.dx, $0.dy) >= 0.5 }
        guard !legs.isEmpty else { return nil }
        corners = [(legs[0].sx, legs[0].sy)]
        var face = facing
        for leg in legs {
            let start = corners.last!
            let end = (start.0 + leg.dx, start.1 + leg.dy)
            let dist = hypot(leg.dx, leg.dy)
            let h = atan2(leg.dx, leg.dy) * 180 / .pi
            corners.append(end)
            cum.append(cum.last! + dist)
            headings.append(h)
            let n = max(1, Int((dist / stepLength).rounded()))
            let delta = PhoneTracker.wrap(h - face)
            let turn = abs(delta) < 45 ? "straight" : abs(delta) > 135 ? "around" : delta > 0 ? "right" : "left"
            let text = turn == "straight" ? "Walk straight \(n) steps." :
                       turn == "around" ? "Turn around, walk \(n) steps." : "Turn \(turn), walk \(n) steps."
            steps.append(Step(turn: turn, count: n, text: text))
            face = h
        }
        steps.append(Step(turn: "arrive", count: 0, text: "You have reached the \(target)."))
    }

    func heading(ofLeg i: Int) -> Double { headings[min(max(i, 0), headings.count - 1)] }

    func stepsToCorner(x: Double, y: Double) -> Int? {
        guard segment + 1 < corners.count else { return nil }
        let c = corners[segment + 1]
        return Int((hypot(c.0 - x, c.1 - y) / stepLength).rounded())
    }

    func update(x: Double, y: Double) -> [Event] {
        guard active else { return [] }
        var out: [Event] = []
        locate(x, y)
        if offset > 4 {
            offCount += 1
            if offCount >= 3 && !lost {
                lost = true
                out.append(.say("I'm not sure where we are. Say where you are to re-anchor.", "uncertain", nil))
            }
            return out
        }
        offCount = 0
        if lost && offset < 2.4 { lost = false; out.append(.say("Back on the route.", "navigating", nil)) }
        if total - progress <= 2 * stepLength {
            active = false
            out.append(.arrived("You have reached the \(target)."))
            return out
        }
        for k in 1..<max(headings.count, 1) {
            let ahead = cum[k] - progress
            if ahead < -1 { continue }
            let n = ahead / stepLength
            let turn = steps[k].turn
            let verb = turn == "around" ? "Turn around" : "Turn \(turn)"
            if n <= 1.5 && !turned.contains(k) {
                turned.insert(k); warned.insert(k)
                out.append(.say("\(verb) now, then walk \(steps[k].count) steps.", "turn_now", 150))
            } else if n <= 5 && !warned.contains(k) {
                warned.insert(k)
                out.append(.say("In \(max(1, Int(n.rounded()))) steps, \(verb.lowercased()).", "turn_now",
                                Int(max(150, min(800, 150 + n * 65)))))
            }
            break
        }
        return out
    }

    private func locate(_ x: Double, _ y: Double) {
        var best: (Int, Double, Double)?
        for j in max(0, segment - 1)..<headings.count {
            let a = corners[j], b = corners[j + 1]
            let dx = b.0 - a.0, dy = b.1 - a.1, len2 = dx * dx + dy * dy
            let t = len2 == 0 ? 0 : max(0, min(1, ((x - a.0) * dx + (y - a.1) * dy) / len2))
            let d = hypot(x - (a.0 + t * dx), y - (a.1 + t * dy))
            if best == nil || d < best!.2 - 1e-9 { best = (j, t, d) }
        }
        guard let (j, t, d) = best else { return }
        segment = j
        progress = cum[j] + t * (cum[j + 1] - cum[j])
        offset = d
    }
}

// MARK: - Buzz coach (store/haptics.py)

struct Coach {
    private var aligned = false
    private var last: [String: Double] = [:]
    private var leg: Int?
    private var arrivedSent = false
    private weak var seen: Navigation?

    private mutating func due(_ cue: String, _ every: Double) -> Bool {
        let now = Date().timeIntervalSince1970
        if now - (last[cue] ?? 0) >= every { last[cue] = now; return true }
        return false
    }

    mutating func update(nav: Navigation?, facing: Double, x: Double, y: Double, stepLength: Double,
                         uncertain: Bool) -> (hint: [String: Any], cue: String?) {
        guard let nav else { aligned = false; leg = nil; arrivedSent = false; return (["active": false], nil) }
        if nav !== seen { self = Coach(); seen = nav; leg = nav.segment }
        if !nav.active {
            if !arrivedSent { arrivedSent = true; return (["arrived": true, "target": nav.target], "arrived") }
            return (["arrived": true, "target": nav.target], nil)
        }
        if uncertain {
            return (["active": true, "lost": true, "target": nav.target], due("lost", 4) ? "lost" : nil)
        }
        let error = PhoneTracker.wrap(nav.heading(ofLeg: nav.segment) - facing)
        let stepsLeft = nav.stepsToCorner(x: x, y: y)
        let nextTurn = nav.segment + 1 < nav.steps.count - 1 ? nav.steps[nav.segment + 1].turn : nil
        var hint: [String: Any] = ["active": true, "error_deg": error, "target": nav.target]
        if let s = stepsLeft { hint["steps_left"] = s }
        if let t = nextTurn, t != "straight" { hint["next_turn"] = t }
        if leg != nav.segment {
            leg = nav.segment; aligned = false
            let turn = nav.steps[nav.segment].turn
            if ["left", "right", "around"].contains(turn) { return (hint, "turn_" + turn) }
        }
        if abs(error) > 50 || (!aligned && abs(error) > 30) {
            aligned = false
            let cue = error > 0 ? "wrong_right" : "wrong_left"
            hint["state"] = cue
            return (hint, due("wrong", 2.5) ? cue : nil)
        }
        hint["state"] = "on_track"
        if !aligned { aligned = true; last["tick"] = Date().timeIntervalSince1970; return (hint, "on_track") }
        if let t = nextTurn, t != "straight", let s = stepsLeft, (1...4).contains(s) {
            hint["state"] = "turn_soon"
            return (hint, due("turn_soon", 0.35 * Double(s)) ? "turn_soon" : nil)
        }
        return (hint, due("tick", 4) ? "tick" : nil)
    }
}

// MARK: - Commands without a model (app.parse_keywords), also the fallback when Gemini is unavailable

enum PhoneCommands {
    enum Action { case startRoute, stopRoute, remember(String, String?), navigate(String), reanchor(String), find(String), ask(String) }

    static let stop: Set<String> = ["the", "a", "an", "to", "back", "where", "was", "is", "my", "me", "take", "i", "of",
                                    "this", "that", "it", "go", "get", "find", "please", "at", "by", "near", "in", "on",
                                    "and", "did", "we", "place", "spot", "called", "remember", "as"]

    static func words(_ s: String) -> [String] {
        s.lowercased().split { !$0.isLetter && !$0.isNumber }.map(String.init).filter { !stop.contains($0) }
    }

    static func parse(_ text: String, places: [Place]) -> Action {
        var t = text.lowercased().trimmingCharacters(in: .whitespacesAndNewlines)
        while let last = t.last, ".!?".contains(last) { t.removeLast() }
        func after(_ prefixes: [String]) -> String? {
            for p in prefixes where t.hasPrefix(p) { return String(t.dropFirst(p.count)).trimmingCharacters(in: .whitespaces) }
            return nil
        }
        func clean(_ s: String) -> String {
            var v = s
            for a in ["the ", "a ", "an "] where v.hasPrefix(a) { v = String(v.dropFirst(a.count)) }
            return v
        }
        if t.hasPrefix("stop route") || t.hasPrefix("end route") || t.hasPrefix("finish route") { return .stopRoute }
        if t.hasPrefix("start") && t.contains("route") || t.hasPrefix("new route") || t.hasPrefix("begin route") { return .startRoute }
        if let rest = after(["take me back to ", "take me to ", "guide me to ", "go back to ", "go to ", "navigate to ", "bring me to "]) {
            return .navigate(rest.contains("start") || rest.contains("beginning") ? "start" : clean(rest))
        }
        if t == "take me back" || t == "go back" { return .navigate("start") }
        if let rest = after(["i'm at ", "i am at ", "we're at ", "we are at ", "i'm by ", "i'm next to "]) { return .reanchor(clean(rest)) }
        if let rest = after(["where is ", "where's ", "where was ", "find "]) { return .find(clean(rest)) }
        if let rest = after(["remember this spot as ", "remember this place as ", "remember this location as ", "remember this as ",
                             "save this spot as ", "save this location as ", "save this place as ", "save this as ",
                             "mark this as ", "this is ", "these are ", "remember "]) {
            let parts = rest.components(separatedBy: " near ")
            return .remember(clean(parts[0]), parts.count > 1 ? "near " + parts[1] : nil)
        }
        return .ask("Sorry, I didn't catch that. Try \"this is the kitchen\" or \"take me to the kitchen\".")
    }
}
