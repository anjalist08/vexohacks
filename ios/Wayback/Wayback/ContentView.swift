import SwiftUI

struct ContentView: View {
    @StateObject private var guide = Guide()

    var body: some View {
        TabView {
            GuideView(guide: guide)
                .tabItem { Label("Guide", systemImage: "location.north.circle.fill") }
            MapView(guide: guide)
                .tabItem { Label("Map", systemImage: "map.fill") }
            PlacesView(guide: guide)
                .tabItem { Label("Places", systemImage: "mappin.and.ellipse") }
            BandView(guide: guide)
                .tabItem { Label("Band", systemImage: "wave.3.right.circle.fill") }
        }
    }
}

/// Reusable brand emblem displaying the Wayback app logo in a continuous squircle.
struct WaybackLogoMark: View {
    var size: CGFloat = 36

    var body: some View {
        Image("WaybackLogo")
            .resizable()
            .interpolation(.high)
            .scaledToFill()
            .frame(width: size, height: size)
            .clipShape(RoundedRectangle(cornerRadius: size * 0.24, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: size * 0.24, style: .continuous)
                    .strokeBorder(Color.cyan.opacity(0.32), lineWidth: max(1, size * 0.025))
            )
            .accessibilityHidden(true)
    }
}

/// Top brand & live connection header shared on the main Guide screen.
struct WaybackHeader: View {
    @ObservedObject var guide: Guide

    private var linkConnected: Bool {
        guide.phoneOnly ? guide.bandConnectedOnPhone : guide.link == .on
    }

    private var linkText: String {
        if guide.phoneOnly {
            return guide.bandConnectedOnPhone ? "\(BandConfig.name)" : "Scanning…"
        }
        switch guide.link {
        case .off: return "Offline"
        case .connecting: return "Connecting…"
        case .on: return "Laptop linked"
        case .failed: return "Reconnecting…"
        }
    }

    var body: some View {
        HStack(spacing: 12) {
            WaybackLogoMark(size: 38)
            VStack(alignment: .leading, spacing: 1) {
                Text("Wayback")
                    .font(.system(.title3, design: .rounded).weight(.bold))
                Text(guide.phoneOnly ? "iPhone Standalone" : "Wearable Spatial Memory")
                    .font(.caption2)
                    .foregroundStyle(.secondary)
            }
            Spacer()
            if let pct = guide.battery {
                HStack(spacing: 4) {
                    Image(systemName: pct <= 15 ? "battery.25" : pct <= 50 ? "battery.50" : "battery.100")
                    Text("\(pct)%").monospacedDigit()
                }
                .font(.caption.weight(.semibold))
                .padding(.horizontal, 9)
                .padding(.vertical, 5)
                .background(Capsule().fill(Color(.secondarySystemGroupedBackground)))
                .foregroundStyle(pct <= 15 ? .red : .secondary)
            }
            HStack(spacing: 6) {
                Circle()
                    .fill(linkConnected ? Color.green : (guide.link == .off ? Color.secondary.opacity(0.5) : Color.orange))
                    .frame(width: 7, height: 7)
                Text(linkText)
                    .font(.caption.weight(.semibold))
                    .lineLimit(1)
            }
            .padding(.horizontal, 10)
            .padding(.vertical, 5)
            .background(Capsule().fill(Color(.secondarySystemGroupedBackground)))
            .foregroundStyle(linkConnected ? .primary : .secondary)
        }
    }
}

/// The main screen: precision compass dial, live cue, onboarding cards, and Talk control.
struct GuideView: View {
    @ObservedObject var guide: Guide
    @AppStorage("phoneLink") private var phoneLink = ""
    @State private var showLaptopSetup = false

    private var stateAccent: Color {
        switch guide.state {
        case "on": return .green
        case "wrong": return .orange
        case "lost": return .red
        case "done": return .purple
        default: return .cyan
        }
    }

    private var stateBadgeText: String {
        switch guide.state {
        case "on": return "ON TRACK"
        case "wrong": return "ADJUST HEADING"
        case "lost": return "RE-ANCHOR NEEDED"
        case "done": return "ARRIVED"
        default:
            if guide.recording {
                return guide.calibrated ? "RECORDING TRAIL" : "CALIBRATING GYRO"
            }
            return "STANDBY"
        }
    }

    var body: some View {
        ScrollView {
            VStack(spacing: 18) {
                WaybackHeader(guide: guide)

                if guide.link != .on {
                    onboardingCards
                    if !guide.feed.isEmpty {
                        activityFeedCard
                    }
                } else {
                    compassCard
                    controlsDeck
                    activityFeedCard
                }
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 12)
        }
        .background(Color(.systemGroupedBackground))
    }

    // MARK: - Disconnected Onboarding Cards

    private var onboardingCards: some View {
        VStack(spacing: 14) {
            VStack(spacing: 14) {
                WaybackLogoMark(size: 64)
                    .shadow(color: .cyan.opacity(0.25), radius: 12, y: 4)

                VStack(spacing: 6) {
                    Text("Connect \(BandConfig.name)")
                        .font(.system(.title3, design: .rounded).weight(.bold))
                    Text("Double-tap your Vexo band so it blinks blue, then run Wayback directly on this iPhone over Bluetooth.")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                        .multilineTextAlignment(.center)
                }

                Button {
                    guide.startPhoneOnly()
                } label: {
                    HStack(spacing: 8) {
                        Image(systemName: "iphone.radiowaves.left.and.right")
                        Text("Start on iPhone (Bluetooth)")
                            .fontWeight(.semibold)
                    }
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 6)
                }
                .buttonStyle(.borderedProminent)
                .controlSize(.large)

                Text("Add Deepgram & Gemini keys in the Band tab for voice, or use buttons & haptics right away.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .multilineTextAlignment(.center)
            }
            .padding(20)
            .background(
                RoundedRectangle(cornerRadius: 22, style: .continuous)
                    .fill(Color(.secondarySystemGroupedBackground))
            )

            DisclosureGroup(isExpanded: $showLaptopSetup) {
                VStack(alignment: .leading, spacing: 10) {
                    Text("1. Run on your Mac: `python3 main.py --band --phone` (or `--bridge --phone` so this iPhone carries the band).")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .padding(.top, 6)

                    TextField("http://192.168.…:8000/web/phone.html?ws_port=8765&token=…", text: $phoneLink, axis: .vertical)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .font(.caption.monospaced())
                        .padding(10)
                        .background(RoundedRectangle(cornerRadius: 12).fill(Color(.tertiarySystemGroupedBackground)))

                    HStack {
                        Button {
                            if let pasted = UIPasteboard.general.string { phoneLink = pasted }
                        } label: {
                            Label("Paste URL", systemImage: "doc.on.clipboard")
                                .font(.subheadline.weight(.medium))
                        }
                        .buttonStyle(.bordered)

                        Spacer()

                        Button {
                            guide.connect(phoneLink: phoneLink)
                        } label: {
                            Label("Connect Wi-Fi", systemImage: "wifi")
                                .font(.subheadline.weight(.semibold))
                        }
                        .buttonStyle(.borderedProminent)
                        .disabled(phoneLink.isEmpty)
                    }
                }
            } label: {
                Label("Or link with Laptop over Wi-Fi", systemImage: "laptopcomputer.and.iphone")
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(.primary)
            }
            .padding(16)
            .background(
                RoundedRectangle(cornerRadius: 18, style: .continuous)
                    .fill(Color(.secondarySystemGroupedBackground))
            )
        }
    }

    // MARK: - Precision Wayfinding Compass Card

    private var compassCard: some View {
        VStack(spacing: 16) {
            HStack {
                Text(stateBadgeText)
                    .font(.caption2.weight(.bold))
                    .tracking(0.8)
                    .padding(.horizontal, 10)
                    .padding(.vertical, 4)
                    .background(Capsule().fill(stateAccent.opacity(0.16)))
                    .foregroundStyle(stateAccent)

                Spacer()

                if guide.guiding && !guide.guideTarget.isEmpty {
                    Label(guide.guideTarget, systemImage: "flag.checkered")
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(.secondary)
                } else {
                    Text("Heading \(Int(guide.facing.rounded()))°")
                        .font(.caption.monospacedDigit())
                        .foregroundStyle(.secondary)
                }
            }

            ZStack {
                // Soft ambient halo
                Circle()
                    .fill(
                        RadialGradient(
                            colors: [stateAccent.opacity(0.22), stateAccent.opacity(0.02), .clear],
                            center: .center,
                            startRadius: 20,
                            endRadius: 120
                        )
                    )
                    .frame(width: 236, height: 236)

                // Outer bezel ring
                Circle()
                    .stroke(stateAccent.opacity(0.75), lineWidth: 5)
                    .frame(width: 212, height: 212)

                // Compass degree ticks
                ForEach(0..<24, id: \.self) { i in
                    let major = i % 6 == 0
                    Rectangle()
                        .fill(major ? Color.primary.opacity(0.45) : Color.secondary.opacity(0.25))
                        .frame(width: major ? 2 : 1, height: major ? 10 : 5)
                        .offset(y: -96)
                        .rotationEffect(.degrees(Double(i) * 15))
                }

                // Forward marker
                Text("YOU FACE ↑")
                    .font(.system(size: 10, weight: .bold, design: .rounded))
                    .foregroundStyle(.secondary)
                    .padding(.horizontal, 7)
                    .padding(.vertical, 2)
                    .background(Capsule().fill(Color(.secondarySystemGroupedBackground)))
                    .offset(y: -106)

                // Direction pointer
                ZStack {
                    Circle()
                        .fill(stateAccent.opacity(0.14))
                        .frame(width: 112, height: 112)

                    Image(systemName: guide.state == "done" ? "checkmark.seal.fill" : "location.north.fill")
                        .resizable()
                        .scaledToFit()
                        .frame(width: 68, height: 68)
                        .foregroundStyle(stateAccent.gradient)
                        .rotationEffect(.degrees(guide.state == "done" ? 0 : guide.arrowDegrees))
                        .animation(.spring(response: 0.28, dampingFraction: 0.78), value: guide.arrowDegrees)
                        .shadow(color: stateAccent.opacity(0.35), radius: 8, y: 2)
                }
            }
            .frame(height: 236)
            .accessibilityHidden(true)

            VStack(spacing: 6) {
                Text(guide.big)
                    .font(.system(.title2, design: .rounded).weight(.bold))
                    .multilineTextAlignment(.center)
                Text(guide.sub)
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                    .multilineTextAlignment(.center)
            }
        }
        .padding(20)
        .background(
            RoundedRectangle(cornerRadius: 24, style: .continuous)
                .fill(Color(.secondarySystemGroupedBackground))
        )
    }

    // MARK: - Voice & Telemetry Controls Deck

    private var controlsDeck: some View {
        VStack(spacing: 12) {
            Button {
                guide.talk()
            } label: {
                HStack(spacing: 10) {
                    Image(systemName: guide.voiceEngine.listening ? "waveform.circle.fill" : "mic.fill")
                        .font(.title3)
                    Text(guide.voiceEngine.listening ? "Listening… Tap to Finish" : "Tap to Talk")
                        .font(.headline)
                }
                .frame(maxWidth: .infinity)
                .padding(.vertical, 10)
            }
            .buttonStyle(.borderedProminent)
            .tint(guide.voiceEngine.listening ? .indigo : .accentColor)

            Text("Or double-tap \(BandConfig.name) on your wrist to talk eyes-free.")
                .font(.caption)
                .foregroundStyle(.secondary)

            if !guide.voice.isEmpty {
                HStack(alignment: .top, spacing: 10) {
                    Image(systemName: "quote.bubble.fill")
                        .foregroundStyle(.tint)
                        .padding(.top, 2)
                    Text(guide.voice)
                        .font(.subheadline)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
                .padding(14)
                .background(
                    RoundedRectangle(cornerRadius: 16, style: .continuous)
                        .fill(Color(.secondarySystemGroupedBackground))
                )
            }

            // 3-pill telemetry strip
            HStack(spacing: 10) {
                telemetryTile(
                    icon: guide.recording ? "record.circle.fill" : "pause.circle.fill",
                    title: guide.recording ? (guide.calibrated ? "Recording" : "Hold Still") : "Idle",
                    value: "\(guide.steps) steps",
                    tint: guide.recording ? (guide.calibrated ? .green : .orange) : .secondary
                )
                telemetryTile(
                    icon: "mappin.and.ellipse",
                    title: "Saved",
                    value: "\(guide.places.count) \(guide.places.count == 1 ? "place" : "places")",
                    tint: .purple
                )
                Button {
                    guide.buzzing.toggle()
                } label: {
                    VStack(alignment: .leading, spacing: 4) {
                        HStack(spacing: 5) {
                            Image(systemName: guide.buzzing ? "iphone.radiowaves.left.and.right" : "iphone.slash")
                                .foregroundStyle(guide.buzzing ? .orange : .secondary)
                            Text("Haptics")
                                .font(.caption2.weight(.semibold))
                                .foregroundStyle(.secondary)
                        }
                        Text(guide.buzzing ? "Buzz On" : "Muted")
                            .font(.subheadline.weight(.semibold))
                            .foregroundStyle(.primary)
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(12)
                    .background(
                        RoundedRectangle(cornerRadius: 16, style: .continuous)
                            .fill(Color(.secondarySystemGroupedBackground))
                    )
                }
                .buttonStyle(.plain)
            }

            if !guide.bandStatus.isEmpty {
                HStack(spacing: 8) {
                    Image(systemName: guide.bandConnectedOnPhone ? "checkmark.circle.fill" : "dot.radiowaves.left.and.right")
                        .foregroundStyle(guide.bandConnectedOnPhone ? .green : .orange)
                    Text(guide.bandStatus)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .frame(maxWidth: .infinity, alignment: .leading)
                    if !guide.bandConnectedOnPhone && guide.carryingBand {
                        Button("Rescan") { guide.resetBandBluetooth() }
                            .font(.caption.weight(.semibold))
                            .buttonStyle(.bordered)
                            .controlSize(.mini)
                    }
                }
                .padding(.horizontal, 14)
                .padding(.vertical, 10)
                .background(
                    RoundedRectangle(cornerRadius: 14, style: .continuous)
                        .fill(Color(.secondarySystemGroupedBackground))
                )
            }
        }
    }

    private func telemetryTile(icon: String, title: String, value: String, tint: Color) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(spacing: 5) {
                Image(systemName: icon)
                    .foregroundStyle(tint)
                Text(title)
                    .font(.caption2.weight(.semibold))
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
            }
            Text(value)
                .font(.subheadline.weight(.semibold).monospacedDigit())
                .lineLimit(1)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(12)
        .background(
            RoundedRectangle(cornerRadius: 16, style: .continuous)
                .fill(Color(.secondarySystemGroupedBackground))
        )
    }

    // MARK: - Live Activity & Command Feed

    private static let feedTimeFormatter: DateFormatter = {
        let f = DateFormatter()
        f.dateFormat = "HH:mm:ss"
        return f
    }()

    private func feedColor(_ tint: String) -> Color {
        switch tint {
        case "blue": return .blue
        case "green": return .green
        case "purple": return .purple
        case "cyan": return .cyan
        case "indigo": return .indigo
        case "orange": return .orange
        case "red": return .red
        default: return .secondary
        }
    }

    private func feedKindTag(_ kind: FeedItem.Kind) -> String {
        switch kind {
        case .heard: return "VOICE"
        case .action: return "ACTION"
        case .buzz: return "HAPTIC"
        case .band: return "VEXO"
        }
    }

    private var activityFeedCard: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Label("Live Activity", systemImage: "list.bullet.rectangle.portrait.fill")
                    .font(.subheadline.weight(.bold))
                if !guide.feed.isEmpty {
                    Text("\(guide.feed.count)")
                        .font(.caption2.weight(.bold).monospacedDigit())
                        .padding(.horizontal, 7)
                        .padding(.vertical, 2)
                        .background(Capsule().fill(Color.accentColor.opacity(0.16)))
                        .foregroundStyle(Color.accentColor)
                }
                Spacer()
                if !guide.feed.isEmpty {
                    Button("Clear") {
                        withAnimation(.easeOut(duration: 0.2)) {
                            guide.clearFeed()
                        }
                    }
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.secondary)
                }
            }

            if guide.feed.isEmpty {
                HStack(spacing: 10) {
                    Image(systemName: "waveform.badge.mic")
                        .font(.title3)
                        .foregroundStyle(.secondary)
                    Text("Spoken commands, route & landmark actions, turn buzzes, and Vexo alerts will appear here live.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                .padding(.vertical, 6)
            } else {
                VStack(spacing: 0) {
                    ForEach(Array(guide.feed.prefix(25).enumerated()), id: \.element.id) { idx, item in
                        let color = feedColor(item.tint)
                        HStack(alignment: .top, spacing: 11) {
                            ZStack {
                                RoundedRectangle(cornerRadius: 9, style: .continuous)
                                    .fill(color.opacity(0.15))
                                    .frame(width: 32, height: 32)
                                Image(systemName: item.icon)
                                    .font(.system(size: 14, weight: .semibold))
                                    .foregroundStyle(color)
                            }
                            .padding(.top, 1)

                            VStack(alignment: .leading, spacing: 3) {
                                HStack(alignment: .firstTextBaseline, spacing: 6) {
                                    Text(feedKindTag(item.kind))
                                        .font(.system(size: 9, weight: .bold, design: .rounded))
                                        .tracking(0.5)
                                        .padding(.horizontal, 5)
                                        .padding(.vertical, 1.5)
                                        .background(Capsule().fill(color.opacity(0.14)))
                                        .foregroundStyle(color)

                                    Spacer()

                                    Text(Self.feedTimeFormatter.string(from: item.time))
                                        .font(.caption2.monospacedDigit())
                                        .foregroundStyle(.tertiary)
                                }

                                Text(item.title)
                                    .font(.subheadline.weight(.medium))
                                    .foregroundStyle(.primary)
                                    .fixedSize(horizontal: false, vertical: true)

                                if let detail = item.detail, !detail.isEmpty {
                                    Text(detail)
                                        .font(.caption)
                                        .foregroundStyle(.secondary)
                                        .fixedSize(horizontal: false, vertical: true)
                                }
                            }
                        }
                        .padding(.vertical, 9)

                        if idx < min(guide.feed.count, 25) - 1 {
                            Divider()
                                .padding(.leading, 43)
                        }
                    }
                }
            }
        }
        .padding(16)
        .background(
            RoundedRectangle(cornerRadius: 20, style: .continuous)
                .fill(Color(.secondarySystemGroupedBackground))
        )
    }
}

#Preview { ContentView() }
