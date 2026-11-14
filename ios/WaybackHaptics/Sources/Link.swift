import Foundation

/// Listens to main.py's WebSocket (the same feed the map page uses) and turns its events into
/// haptic cues. It only listens: it never sends commands.
@MainActor
final class Link: ObservableObject {
    @Published var status = "not connected"
    @Published var lastCue = "–"
    @Published var log: [String] = []

    private var task: URLSessionWebSocketTask?
    private var wanted = false
    private var url: URL?
    private var lastDirectionAt = Date.distantPast

    /// Accepts "172.20.10.13:8790", "ws://172.20.10.13:8790", or a pasted map link like
    /// "http://172.20.10.13:8091/web/trail.html?ws_port=8790" (uses its ws_port).
    static func websocketURL(from address: String) -> URL? {
        var text = address.trimmingCharacters(in: .whitespacesAndNewlines)
        if text.isEmpty { return nil }
        if !text.contains("://") { text = "ws://" + text }
        guard let parsed = URLComponents(string: text), let host = parsed.host, !host.isEmpty else { return nil }
        var port = parsed.port ?? 8790
        if let wsPort = parsed.queryItems?.first(where: { $0.name == "ws_port" })?.value, let p = Int(wsPort) {
            port = p
        } else if parsed.scheme == "http" || parsed.scheme == "https" {
            port = 8790      // a map link without ws_port: main.py's default haptics port here
        }
        var out = URLComponents()
        out.scheme = "ws"
        out.host = host
        out.port = port
        return out.url
    }

    func connect(_ address: String) {
        guard let u = Link.websocketURL(from: address) else {
            status = "Can't read that address. Type what main.py prints, e.g. 172.20.10.13:8790"
            return
        }
        task?.cancel(with: .goingAway, reason: nil)
        task = nil
        url = u
        wanted = true
        open()
    }

    func disconnect() {
        wanted = false
        task?.cancel(with: .goingAway, reason: nil)
        task = nil
        status = "not connected"
    }

    private func open() {
        guard wanted, let url else { return }
        status = "connecting to \(url.absoluteString)…"
        let t = URLSession.shared.webSocketTask(with: url)
        task = t
        t.resume()
        receive(t)
        // If nothing arrives in 5 s, say what usually causes it.
        Task { @MainActor in
            try? await Task.sleep(nanoseconds: 5_000_000_000)
            if self.task === t, self.status.hasPrefix("connecting") {
                self.status = "No answer from \(url.absoluteString). Check: main.py runs with --host hotspot, the Mac is on this phone's hotspot, and Settings > Privacy & Security > Local Network > Wayback is on."
            }
        }
    }

    private func receive(_ t: URLSessionWebSocketTask) {
        t.receive { [weak self] result in
            Task { @MainActor in
                guard let self, self.task === t else { return }
                switch result {
                case .success(let message):
                    if !self.status.hasPrefix("connected") { self.status = "connected to \(self.url?.absoluteString ?? "")" }
                    if case .string(let s) = message { self.handle(s) }
                    self.receive(t)
                case .failure(let error):
                    self.status = "Could not connect to \(self.url?.absoluteString ?? ""): \(error.localizedDescription). Retrying…"
                    self.task = nil
                    try? await Task.sleep(nanoseconds: 2_000_000_000)
                    self.open()
                }
            }
        }
    }

    private func handle(_ text: String) {
        guard let data = text.data(using: .utf8),
              let msg = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let type = msg["type"] as? String else { return }
        switch type {
        case "led":
            switch msg["state"] as? String ?? "" {
            case "route_started": fire(.start)
            case "landmark_saved": fire(.saved)
            case "navigating": fire(.navigating)
            case "arrived": fire(.arrived)
            case "uncertain": fire(.unsure)
            case "turn_now":
                // A spoken "Turn left/right" usually follows; give it a moment to win.
                Task { @MainActor in
                    try? await Task.sleep(nanoseconds: 700_000_000)
                    if Date().timeIntervalSince(self.lastDirectionAt) > 1.5 { self.fire(.turn) }
                }
            default: break
            }
        case "say":
            // Only the first sentence: "Turn around, walk 24 steps. Then turn right, …"
            let first = (msg["text"] as? String ?? "").lowercased().components(separatedBy: ".").first ?? ""
            if first.contains("turn around") { direction(.turnAround) }
            else if first.contains("turn left") { direction(.turnLeft) }
            else if first.contains("turn right") { direction(.turnRight) }
        default: break
        }
    }

    private func direction(_ cue: Cue) {
        lastDirectionAt = Date()
        fire(cue)
    }

    func fire(_ cue: Cue) {
        Haptics.shared.play(cue)
        lastCue = cue.title
        let stamp = Date().formatted(date: .omitted, time: .standard)
        log.insert("\(stamp)  \(cue.title)", at: 0)
        if log.count > 50 { log.removeLast() }
    }
}
