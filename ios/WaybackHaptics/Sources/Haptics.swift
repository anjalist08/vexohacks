import CoreHaptics
import UIKit

/// The haptic vocabulary. Each cue feels different, so you can tell them apart in a pocket:
/// start = two light taps, saved = one firm buzz, left = two sharp taps, right = three sharp
/// taps, around = a long buzz then two taps, arrived = rising buzz + celebration taps,
/// unsure = two slow heavy thuds, navigating = one soft tap.
enum Cue: String, CaseIterable, Identifiable {
    case start, saved, navigating, turnLeft, turnRight, turnAround, turn, arrived, unsure
    var id: String { rawValue }

    var title: String {
        switch self {
        case .start: return "Route started"
        case .saved: return "Landmark saved"
        case .navigating: return "Guiding back"
        case .turnLeft: return "Turn left"
        case .turnRight: return "Turn right"
        case .turnAround: return "Turn around"
        case .turn: return "Turn now"
        case .arrived: return "Arrived"
        case .unsure: return "Position unsure"
        }
    }
}

final class Haptics {
    static let shared = Haptics()
    private var engine: CHHapticEngine?

    private init() { startEngine() }

    private func startEngine() {
        guard CHHapticEngine.capabilitiesForHardware().supportsHaptics else { return }
        do {
            let e = try CHHapticEngine()
            e.isAutoShutdownEnabled = false
            e.playsHapticsOnly = true
            e.resetHandler = { [weak self] in try? self?.engine?.start() }
            try e.start()
            engine = e
        } catch {
            engine = nil
        }
    }

    private func tap(_ t: Double, _ intensity: Float = 1.0, _ sharpness: Float = 0.8) -> CHHapticEvent {
        CHHapticEvent(eventType: .hapticTransient,
                      parameters: [CHHapticEventParameter(parameterID: .hapticIntensity, value: intensity),
                                   CHHapticEventParameter(parameterID: .hapticSharpness, value: sharpness)],
                      relativeTime: t)
    }

    private func buzz(_ t: Double, _ d: Double, _ intensity: Float = 1.0, _ sharpness: Float = 0.3) -> CHHapticEvent {
        CHHapticEvent(eventType: .hapticContinuous,
                      parameters: [CHHapticEventParameter(parameterID: .hapticIntensity, value: intensity),
                                   CHHapticEventParameter(parameterID: .hapticSharpness, value: sharpness)],
                      relativeTime: t, duration: d)
    }

    private func events(for cue: Cue) -> [CHHapticEvent] {
        switch cue {
        case .start: return [tap(0, 0.6, 0.5), tap(0.15, 0.6, 0.5)]
        case .saved: return [buzz(0, 0.35, 1.0, 0.4)]
        case .navigating: return [tap(0, 0.5, 0.3)]
        case .turnLeft: return [tap(0, 1, 1), tap(0.14, 1, 1)]
        case .turnRight: return [tap(0, 1, 1), tap(0.14, 1, 1), tap(0.28, 1, 1)]
        case .turnAround: return [buzz(0, 0.5, 1, 0.5), tap(0.65, 1, 1), tap(0.8, 1, 1)]
        case .turn: return [tap(0, 1, 1)]
        case .arrived: return [buzz(0, 0.6, 0.8, 0.2), tap(0.75, 1, 1), tap(0.9, 1, 1), tap(1.05, 1, 1)]
        case .unsure: return [tap(0, 1, 0.1), tap(0.5, 1, 0.1)]
        }
    }

    func play(_ cue: Cue) {
        guard let engine else { fallback(cue); return }
        do {
            try engine.start()
            let pattern = try CHHapticPattern(events: events(for: cue), parameters: [])
            try engine.makePlayer(with: pattern).start(atTime: CHHapticTimeImmediate)
        } catch {
            fallback(cue)
        }
    }

    /// Devices without Core Haptics: the closest system feedback.
    private func fallback(_ cue: Cue) {
        switch cue {
        case .arrived, .saved: UINotificationFeedbackGenerator().notificationOccurred(.success)
        case .unsure: UINotificationFeedbackGenerator().notificationOccurred(.warning)
        default: UIImpactFeedbackGenerator(style: .heavy).impactOccurred()
        }
    }
}
