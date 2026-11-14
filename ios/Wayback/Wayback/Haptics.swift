import CoreHaptics
import UIKit

/// Plays the guidance cues as real iPhone vibration (Core Haptics).
/// The patterns match store/haptics.py: on, off, on, ... in milliseconds.
final class Haptics {
    static let patterns: [String: [Double]] = [
        "wrong_left": [120, 120, 120],
        "wrong_right": [120, 120, 120, 120, 120],
        "on_track": [600],
        "tick": [50],
        "turn_soon": [80],
        "turn_left": [500, 150, 150],
        "turn_right": [500, 150, 150, 150, 150],
        "turn_around": [500, 150, 500],
        "arrived": [700, 200, 700, 200, 700],
        "lost": [100, 60, 100, 60, 100, 60, 100, 60, 100],
    ]

    /// Left cues feel softer (lower sharpness), right cues crisper, so the two directions differ by feel too.
    private static func sharpness(for cue: String) -> Float {
        if cue.hasSuffix("left") { return 0.2 }
        if cue.hasSuffix("right") { return 0.9 }
        if cue == "tick" || cue == "turn_soon" { return 0.6 }
        return 0.45
    }

    private var engine: CHHapticEngine?
    private let fallback = UIImpactFeedbackGenerator(style: .heavy)
    let supported = CHHapticEngine.capabilitiesForHardware().supportsHaptics

    init() { start() }

    private func start() {
        guard supported else { return }
        do {
            let engine = try CHHapticEngine()
            engine.playsHapticsOnly = true
            engine.isAutoShutdownEnabled = true
            engine.resetHandler = { [weak self] in try? self?.engine?.start() }
            engine.stoppedHandler = { _ in }
            try engine.start()
            self.engine = engine
        } catch {
            engine = nil
        }
    }

    func play(_ cue: String) {
        guard let pattern = Haptics.patterns[cue] else { return }
        guard let engine else {                      // no Core Haptics: tap once per "on" part
            fallback.impactOccurred()
            return
        }
        var events: [CHHapticEvent] = []
        var t: Double = 0
        let sharp = Haptics.sharpness(for: cue)
        for (i, ms) in pattern.enumerated() {
            if i % 2 == 0 {
                let intensity: Float = cue == "tick" ? 0.45 : 1.0
                events.append(CHHapticEvent(
                    eventType: .hapticContinuous,
                    parameters: [CHHapticEventParameter(parameterID: .hapticIntensity, value: intensity),
                                 CHHapticEventParameter(parameterID: .hapticSharpness, value: sharp)],
                    relativeTime: t, duration: ms / 1000))
            }
            t += ms / 1000
        }
        do {
            try engine.start()
            let player = try engine.makePlayer(with: CHHapticPattern(events: events, parameters: []))
            try player.start(atTime: CHHapticTimeImmediate)
        } catch {
            fallback.impactOccurred()
        }
    }
}
