import Foundation
import SwiftUI
import UIKit

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

    let haptics = Haptics()
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
    }

    func disconnect() {
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
        task?.send(.string(#"{"type":"talk"}"#)) { _ in }
    }

    func tryCue(_ cue: String) {
        haptics.play(cue)
        lastCue = cue
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
            }
        case "haptic_hint":
            show(hint: m)
        case "voice":
            let s = m["state"] as? String ?? ""
            switch s {
            case "listening": voice = "Listening… speak now"
            case "heard": voice = "Heard: " + (m["text"] as? String ?? "")
            case "thinking": voice = "Understanding…"
            case "done": voice = m["say"] as? String ?? ""
            default: voice = m["text"] as? String ?? ""
            }
        case "say":
            voice = m["text"] as? String ?? ""
        default:
            break
        }
    }

    private func show(hint m: [String: Any]) {
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
