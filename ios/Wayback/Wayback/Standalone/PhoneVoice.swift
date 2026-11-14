import AVFoundation
import AudioToolbox
import Foundation
import Security

/// API keys on the phone: typed once in the Band tab, kept in the iOS Keychain (never in code or git).
enum KeyStore {
    static let names = ["deepgram", "gemini", "elevenlabs"]

    static func get(_ name: String) -> String? {
        let q: [String: Any] = [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: "wayback",
                                kSecAttrAccount as String: name, kSecReturnData as String: true]
        var out: AnyObject?
        guard SecItemCopyMatching(q as CFDictionary, &out) == errSecSuccess, let d = out as? Data else { return nil }
        let v = String(data: d, encoding: .utf8)?.trimmingCharacters(in: .whitespacesAndNewlines)
        return (v?.isEmpty ?? true) ? nil : v
    }

    static func set(_ name: String, _ value: String) {
        let q: [String: Any] = [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: "wayback",
                                kSecAttrAccount as String: name]
        SecItemDelete(q as CFDictionary)
        let v = value.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !v.isEmpty else { return }
        var add = q
        add[kSecValueData as String] = Data(v.utf8)
        add[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        SecItemAdd(add as CFDictionary, nil)
    }
}

/// Voice on the phone: double-tap the band (or Talk) -> the band's mic -> Deepgram live text ->
/// Gemini 4 picks the action (keyword fallback) -> PhoneBrain runs it -> ElevenLabs speaks
/// (or the iPhone's own voice). Double-tap again, or pause 2 s after speaking, to stop.
@MainActor
final class PhoneVoice: NSObject, AVAudioPlayerDelegate {
    weak var guide: Guide?
    private(set) var listening = false
    private var busy = false
    private var socket: URLSessionWebSocketTask?
    private var finals: [String] = []
    private var lastText = Date.distantPast
    private var startedAt = Date()
    private var watch: Timer?
    private let synth = AVSpeechSynthesizer()
    private var player: AVAudioPlayer?

    static let geminiModel = "gemini-4-hydrogen"
    static let elevenVoice = "SAz9YHcvj6GT2YYXdXww"       // River, as on the laptop

    init(guide: Guide) {
        self.guide = guide
        super.init()
        try? AVAudioSession.sharedInstance().setCategory(.playback, options: [.duckOthers])
    }

    // MARK: listening

    func doubleTap() {
        if listening { stopListening() } else if !busy { startListening() }
    }

    private func startListening() {
        guard let key = KeyStore.get("deepgram") else {
            speak("Add your Deepgram key in the Band tab to use voice. You can still type or tap commands.")
            return
        }
        var c = URLComponents(string: "wss://api.deepgram.com/v1/listen")!
        // the same query the kit's speech.py sends: raw Opus packets from the band, 16 kHz mono
        c.queryItems = [("model", "nova-3"), ("language", "en"), ("encoding", "opus"), ("sample_rate", "16000"),
                        ("channels", "1"), ("interim_results", "true"), ("smart_format", "true"),
                        ("endpointing", "100"), ("mip_opt_out", "true"), ("keyterm", "landmark")]
            .map { URLQueryItem(name: $0.0, value: $0.1) }
        var req = URLRequest(url: c.url!)
        req.setValue("Token " + key, forHTTPHeaderField: "Authorization")   // header only, never in the URL
        let ws = URLSession.shared.webSocketTask(with: req)
        socket = ws
        finals = []
        ws.resume()
        receive(ws)
        listening = true
        busy = true
        startedAt = Date()
        lastText = .distantPast
        guide?.runOnBand(["op": "configure", "args": ["audio": true]])    // the band's light goes solid blue
        AudioServicesPlaySystemSound(1113)
        guide?.voice = "Listening… speak, then double-tap again (or pause)."
        watch?.invalidate()
        watch = Timer.scheduledTimer(withTimeInterval: 0.2, repeats: true) { [weak self] _ in
            MainActor.assumeIsolated {
                guard let self, self.listening else { return }
                let quiet = !self.finals.isEmpty && Date().timeIntervalSince(self.lastText) > 2
                if quiet || Date().timeIntervalSince(self.startedAt) > 15 { self.stopListening() }
            }
        }
    }

    /// One Opus packet from the band, relayed by BandLink.
    func audio(_ m: [String: Any]) {
        guard listening, let s = m["opus"] as? String, let d = Data(base64Encoded: s) else { return }
        socket?.send(.data(d)) { _ in }
    }

    private func receive(_ ws: URLSessionWebSocketTask) {
        ws.receive { [weak self] result in
            Task { @MainActor in
                guard let self, self.socket === ws else { return }
                guard case .success(let msg) = result else { return }
                if case .string(let text) = msg,
                   let d = text.data(using: .utf8),
                   let j = try? JSONSerialization.jsonObject(with: d) as? [String: Any],
                   let alt = ((j["channel"] as? [String: Any])?["alternatives"] as? [[String: Any]])?.first,
                   let words = alt["transcript"] as? String, !words.isEmpty {
                    self.lastText = Date()
                    if j["is_final"] as? Bool == true { self.finals.append(words) }
                    self.guide?.voice = "Heard: " + (self.finals + ((j["is_final"] as? Bool == true) ? [] : [words])).joined(separator: " ")
                }
                self.receive(ws)
            }
        }
    }

    private func stopListening() {
        guard listening else { return }
        listening = false
        watch?.invalidate()
        guide?.runOnBand(["op": "configure", "args": ["audio": false]])
        AudioServicesPlaySystemSound(1114)
        socket?.send(.string(#"{"type":"CloseStream"}"#)) { _ in }
        Task { @MainActor in
            try? await Task.sleep(nanoseconds: 1_200_000_000)          // let the last words arrive
            socket?.cancel(with: .normalClosure, reason: nil)
            socket = nil
            let words = finals.joined(separator: " ").trimmingCharacters(in: .whitespaces)
            if words.isEmpty {
                busy = false
                speak("I didn't hear anything. Double-tap, then speak right away.")
                return
            }
            guide?.voice = "Heard: \(words)"
            await understand(words)
            busy = false
        }
    }

    // MARK: understanding (Gemini 4 function calling, keyword fallback)

    func understand(_ text: String) async {
        guard let brain = guide?.brain else { return }
        if let key = KeyStore.get("gemini"), let action = await askGemini(text, key: key) {
            brain.run(action)
        } else {
            brain.command(text)
        }
    }

    private func askGemini(_ text: String, key: String) async -> PhoneCommands.Action? {
        let places = guide?.places.map { "\($0.id)=\($0.label)" }.joined(separator: "; ") ?? ""
        let system = """
        You are the voice intent router for a wearable indoor spatial-memory band. Pick exactly one tool call.
        Never invent coordinates, step counts or turns; code computes them.
        Saved places (id=label): \(places.isEmpty ? "none" : places).
        Use a place's exact id for navigate_to and reanchor. "Take me back" with no place means target "start".
        The text comes from a small wrist microphone and is often misheard: read it as the closest command
        (for example "same dislocation" means "save this location"). To save a place with no name said,
        use the label "spot N". Only if nothing fits, call ask_user with a short question.
        """
        func fn(_ name: String, _ desc: String, _ props: [String: String], _ required: [String]) -> [String: Any] {
            var d: [String: Any] = ["name": name, "description": desc]
            if !props.isEmpty {
                d["parameters"] = ["type": "OBJECT", "properties": props.mapValues { ["type": "STRING", "description": $0] },
                                   "required": required]
            }
            return d
        }
        let tools: [[String: Any]] = [
            fn("start_route", "Start recording a new route from here.", [:], []),
            fn("stop_route", "Stop recording the route.", [:], []),
            fn("remember_landmark", "Save where the user stands now under a name.", ["label": "the place's name", "note": "anything else said about it"], ["label"]),
            fn("navigate_to", "Guide the user to a saved place, or back to the start.", ["target": "a place id, or start"], ["target"]),
            fn("reanchor", "The user says they are at a saved place.", ["landmark_id": "a place id"], ["landmark_id"]),
            fn("find_landmark", "Say where a saved place is.", ["query": "what the user asked about"], ["query"]),
            fn("ask_user", "Ask a short clarifying question.", ["question": "the question"], ["question"]),
        ]
        let body: [String: Any] = [
            "systemInstruction": ["parts": [["text": system]]],
            "contents": [["role": "user", "parts": [["text": text]]]],
            "tools": [["functionDeclarations": tools]],
            "toolConfig": ["functionCallingConfig": ["mode": "ANY"]],
        ]
        var req = URLRequest(url: URL(string: "https://generativelanguage.googleapis.com/v1beta/models/\(PhoneVoice.geminiModel):generateContent")!)
        req.httpMethod = "POST"
        req.setValue(key, forHTTPHeaderField: "x-goog-api-key")           // header only, never in the URL
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = try? JSONSerialization.data(withJSONObject: body)
        req.timeoutInterval = 8
        guard let (data, resp) = try? await URLSession.shared.data(for: req),
              (resp as? HTTPURLResponse)?.statusCode == 200,
              let j = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let parts = (((j["candidates"] as? [[String: Any]])?.first?["content"] as? [String: Any])?["parts"] as? [[String: Any]]),
              let call = parts.compactMap({ $0["functionCall"] as? [String: Any] }).first,
              let name = call["name"] as? String else { return nil }
        let a = call["args"] as? [String: Any] ?? [:]
        let s = { (k: String) in (a[k] as? String) ?? "" }
        switch name {
        case "start_route": return .startRoute
        case "stop_route": return .stopRoute
        case "remember_landmark": return .remember(s("label"), a["note"] as? String)
        case "navigate_to": return .navigate(s("target"))
        case "reanchor": return .reanchor(s("landmark_id"))
        case "find_landmark": return .find(s("query"))
        case "ask_user": return .ask(s("question"))
        default: return nil
        }
    }

    // MARK: speaking (ElevenLabs River, else the iPhone's voice)

    func speak(_ text: String) {
        guide?.voice = text
        guard let key = KeyStore.get("elevenlabs") else { speakLocally(text); return }
        Task { @MainActor in
            var req = URLRequest(url: URL(string: "https://api.elevenlabs.io/v1/text-to-speech/\(PhoneVoice.elevenVoice)")!)
            req.httpMethod = "POST"
            req.setValue(key, forHTTPHeaderField: "xi-api-key")
            req.setValue("application/json", forHTTPHeaderField: "Content-Type")
            req.setValue("audio/mpeg", forHTTPHeaderField: "Accept")
            req.httpBody = try? JSONSerialization.data(withJSONObject: ["text": text, "model_id": "eleven_turbo_v2_5"])
            req.timeoutInterval = 8
            if let (data, resp) = try? await URLSession.shared.data(for: req),
               (resp as? HTTPURLResponse)?.statusCode == 200,
               let p = try? AVAudioPlayer(data: data) {
                try? AVAudioSession.sharedInstance().setActive(true)
                player?.stop()
                player = p
                p.play()
            } else {
                speakLocally(text)
            }
        }
    }

    private func speakLocally(_ text: String) {
        synth.stopSpeaking(at: .immediate)
        synth.speak(AVSpeechUtterance(string: text))
    }
}
