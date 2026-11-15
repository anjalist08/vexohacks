import SwiftUI

/// Hardware dashboard for Vexo-HACK-80: Bluetooth link, battery, live sensors, haptics tester, and Keychain keys.
struct BandView: View {
    @ObservedObject var guide: Guide

    private let legend: [(cue: String, text: String, dots: String)] = [
        ("wrong_left", "Wrong way: turn left", "• •"),
        ("wrong_right", "Wrong way: turn right", "• • •"),
        ("on_track", "On track (locked on)", "━━━"),
        ("turn_soon", "Turn coming", "· · · ·"),
        ("turn_left", "Turn left now", "━ •"),
        ("turn_right", "Turn right now", "━ • •"),
        ("turn_around", "Turn around", "━ ━"),
        ("arrived", "Stop: arrived", "━ ━ ━"),
        ("lost", "Stop: lost", "•••••"),
    ]

    @State private var keyText: [String: String] = [:]
    @State private var savedNote = ""

    private var linkUp: Bool {
        guide.bandConnectedOnPhone || guide.bandLinkStatus == "connected" || guide.bandLinkStatus == "reconnected"
    }

    private var ledDotColor: Color {
        switch guide.ledState {
        case "route_started", "arrived": return .green
        case "recording": return .orange
        case "landmark_saved": return .purple
        case "navigating", "turn_now", "connected_flash": return .cyan
        case "arrived_party": return .pink
        case "uncertain": return .red
        default: return .secondary.opacity(0.4)
        }
    }

    var body: some View {
        List {
            // Hardware Link Hero Section
                Section {
                    HStack(spacing: 12) {
                        ZStack {
                            RoundedRectangle(cornerRadius: 12, style: .continuous)
                                .fill(linkUp ? Color.green.opacity(0.15) : Color.orange.opacity(0.15))
                                .frame(width: 44, height: 44)
                            Image(systemName: linkUp ? "dot.radiowaves.left.and.right" : "antenna.radiowaves.left.and.right.slash")
                                .font(.title3.weight(.semibold))
                                .foregroundStyle(linkUp ? .green : .orange)
                        }

                        VStack(alignment: .leading, spacing: 2) {
                            HStack(spacing: 6) {
                                Text(guide.bandName)
                                    .font(.headline)
                                Circle()
                                    .fill(ledDotColor)
                                    .frame(width: 8, height: 8)
                            }
                            Text(guide.bandVia.isEmpty ? "Bluetooth Low Energy (GATT)" : guide.bandVia)
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }

                        Spacer()

                        Text(linkUp ? "CONNECTED" : guide.bandLinkStatus.uppercased())
                            .font(.caption2.weight(.bold))
                            .padding(.horizontal, 9)
                            .padding(.vertical, 4)
                            .background(Capsule().fill((linkUp ? Color.green : Color.orange).opacity(0.16)))
                            .foregroundStyle(linkUp ? .green : .orange)
                    }
                    .padding(.vertical, 4)

                    if guide.carryingBand {
                        Label(guide.bandStatus.isEmpty ? "Scanning for \(BandConfig.name)…" : guide.bandStatus,
                              systemImage: guide.bandConnectedOnPhone ? "checkmark.circle.fill" : "wave.3.right")
                            .font(.footnote)
                            .foregroundStyle(guide.bandConnectedOnPhone ? .green : .primary)

                        HStack(spacing: 10) {
                            if guide.bandConnectedOnPhone {
                                Button {
                                    guide.flashBand()
                                } label: {
                                    Label("Flash LED", systemImage: "light.beacon.max.fill")
                                        .frame(maxWidth: .infinity)
                                }
                                .buttonStyle(.borderedProminent)
                                .controlSize(.small)
                            } else {
                                Button {
                                    guide.resetBandBluetooth()
                                } label: {
                                    Label("Reset & Scan Fresh", systemImage: "arrow.clockwise")
                                        .frame(maxWidth: .infinity)
                                }
                                .buttonStyle(.borderedProminent)
                                .controlSize(.small)
                            }

                            Button(role: .destructive) {
                                guide.disconnectBandFromPhone()
                            } label: {
                                Label("Disconnect", systemImage: "xmark.circle")
                                    .frame(maxWidth: .infinity)
                            }
                            .buttonStyle(.bordered)
                            .controlSize(.small)
                        }
                    } else {
                        Button {
                            guide.connectBandFromPhone()
                        } label: {
                            Label("Connect \(BandConfig.name) (iPhone Bluetooth)", systemImage: "antenna.radiowaves.left.and.right")
                                .fontWeight(.semibold)
                                .frame(maxWidth: .infinity)
                        }
                        .buttonStyle(.borderedProminent)

                        Text(guide.bridgeWanted
                             ? "Laptop bridge ready — double-tap \(BandConfig.name) so it blinks blue, then tap Connect."
                             : "Double-tap \(BandConfig.name) until it blinks blue (60 s window), then tap Connect. Do not pair in iOS Settings.")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                } header: {
                    Text("Wearable Link")
                } footer: {
                    Text("Tip: plugging the band briefly into USB-C power also wakes its 60 s Bluetooth window; you can unplug once connected.")
                }

                // Battery & Thermal Section
                Section {
                    if let pct = guide.battery {
                        VStack(alignment: .leading, spacing: 8) {
                            HStack {
                                Label("Battery Charge", systemImage: pct <= 15 ? "battery.25" : "battery.100.bolt")
                                Spacer()
                                Text("\(pct)%")
                                    .font(.headline.monospacedDigit())
                            }
                            ProgressView(value: Double(pct), total: 100)
                                .tint(pct <= 15 ? .red : pct <= 35 ? .orange : .green)
                            HStack {
                                Text([guide.batteryState.capitalized, guide.batteryVolts.map { String(format: "%.2f V", $0) }]
                                    .compactMap { $0 }.filter { !$0.isEmpty }.joined(separator: " · "))
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                                Spacer()
                                if let t = guide.chipTemp {
                                    Text(String(format: "Chip %.0f °C", t))
                                        .font(.caption.monospacedDigit())
                                        .foregroundStyle(.secondary)
                                }
                            }
                            if pct <= 15 && guide.batteryState != "charging" {
                                Label("Low battery — charge \(BandConfig.name) before walking.", systemImage: "exclamationmark.triangle.fill")
                                    .font(.caption)
                                    .foregroundStyle(.red)
                            }
                        }
                        .padding(.vertical, 2)
                    } else {
                        Label("Connect \(BandConfig.name) to view live battery & temperature", systemImage: "battery.0")
                            .font(.footnote)
                            .foregroundStyle(.secondary)
                    }
                } header: {
                    Text("Power & Health")
                }

                // Sensor Telemetry Section
                Section {
                    LabeledContent("Tracker State", value: guide.recording ? (guide.calibrated ? "Recording" : "Calibrating") : "Idle")
                    if !guide.trackSource.isEmpty {
                        LabeledContent("Sensor Fusion", value: guide.trackSource)
                    }
                    LabeledContent("Steps & Distance", value: "\(guide.steps) steps (\(String(format: "%.1f m", Double(guide.steps) * guide.stepLength)))")
                    LabeledContent("Stride Estimate", value: String(format: "%.2f m", guide.stepLength))
                    if guide.level != 0 {
                        LabeledContent("Floor Offset", value: "\(guide.level > 0 ? "+" : "")\(guide.level)F")
                    }
                    LabeledContent("Live Heading", value: String(format: "%.0f°", guide.facing))
                    LabeledContent("Wrist Activity", value: guide.activity.capitalized)
                    LabeledContent("Gyro Bias", value: String(format: "%.2f °/s", guide.gyroBias))
                    LabeledContent("Wrist LED Cue", value: guide.ledState.replacingOccurrences(of: "_", with: " ").capitalized)
                    if guide.uncertain {
                        Label("Heading drifted — stand at a saved spot and say \"I'm at the …\"", systemImage: "exclamationmark.octagon.fill")
                            .font(.caption)
                            .foregroundStyle(.red)
                    }
                } header: {
                    Text("Inertial Telemetry")
                }

                // Core Haptics Tester
                Section {
                    Toggle(isOn: $guide.buzzing) {
                        Label("Pocket Haptic Guidance", systemImage: "iphone.radiowaves.left.and.right")
                    }
                    ForEach(legend, id: \.cue) { item in
                        HStack {
                            Text(item.dots)
                                .font(.footnote.monospaced().weight(.bold))
                                .foregroundStyle(.orange)
                                .frame(width: 68, alignment: .leading)
                            Text(item.text)
                                .font(.subheadline)
                            Spacer()
                            Button("Try") { guide.tryCue(item.cue) }
                                .font(.caption.weight(.semibold))
                                .buttonStyle(.bordered)
                                .controlSize(.small)
                        }
                    }
                } header: {
                    Text("Core Haptics Vocabulary")
                } footer: {
                    Text(guide.haptics.supported
                         ? "Left cues feel softer and right cues crisper. Keep Wayback on screen while walking so iOS plays haptics."
                         : "This device does not support Core Haptics.")
                }

                // iOS Keychain API Keys
                Section {
                    ForEach(KeyStore.names, id: \.self) { name in
                        let hasSaved = KeyStore.get(name) != nil
                        HStack(spacing: 10) {
                            Image(systemName: hasSaved ? "checkmark.seal.fill" : "key.fill")
                                .foregroundStyle(hasSaved ? .green : .secondary)
                            Text(name.capitalized)
                                .frame(width: 84, alignment: .leading)
                            SecureField(hasSaved ? "Saved in Keychain ••••" : "Paste API key", text: Binding(
                                get: { keyText[name] ?? "" }, set: { keyText[name] = $0 }))
                                .textInputAutocapitalization(.never)
                                .autocorrectionDisabled()
                                .font(.footnote)
                        }
                    }
                    Button {
                        for (name, v) in keyText where !v.isEmpty { KeyStore.set(name, v) }
                        keyText = [:]
                        savedNote = "Keys saved securely in this iPhone's Keychain."
                    } label: {
                        Label("Save Keys to Keychain", systemImage: "lock.shield.fill")
                            .fontWeight(.medium)
                    }
                } header: {
                    Text("Voice AI Keys (iPhone Standalone)")
                } footer: {
                    Text(savedNote.isEmpty
                         ? "Deepgram (STT), Gemini 4 (intent tool calling), and ElevenLabs (River voice; optional — falls back to iOS speech). Stored only in iOS Keychain."
                         : savedNote)
                }

                if guide.link == .on {
                    Section {
                        Button(role: .destructive) {
                            guide.disconnect()
                        } label: {
                            Label(guide.phoneOnly ? "Exit iPhone-Only Session" : "Disconnect from Laptop", systemImage: "power")
                        }
                    }
                }
        }
        .navigationTitle("Band #\(BandConfig.number)")
        .navigationBarTitleDisplayMode(.inline)
    }
}

#Preview("Band") {
    NavigationStack {
        BandView(guide: Guide())
    }
}
