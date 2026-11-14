import SwiftUI

/// The band: how it is connected, battery, tracking numbers, and the buzz patterns.
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

    private var linkUp: Bool { guide.bandLinkStatus == "connected" || guide.bandLinkStatus == "reconnected" }

    var body: some View {
        List {
            Section {
                HStack {
                    Text(guide.bandName).font(.headline)
                    Spacer()
                    Text(linkUp ? "connected" : guide.bandLinkStatus)
                        .font(.caption.bold())
                        .foregroundStyle(linkUp ? .green : .orange)
                }
                if !guide.bandVia.isEmpty {
                    LabeledContent("Linked via", value: guide.bandVia)
                }
                if guide.carryingBand {
                    Label(guide.bandStatus.isEmpty ? "Searching…" : guide.bandStatus,
                          systemImage: guide.bandConnectedOnPhone ? "checkmark.circle.fill" : "dot.radiowaves.left.and.right")
                        .font(.footnote)
                        .foregroundStyle(guide.bandConnectedOnPhone ? .green : .primary)
                    if guide.bandConnectedOnPhone {
                        Button { guide.flashBand() } label: {
                            Label("Flash \(BandConfig.name) (test link)", systemImage: "light.beacon.max.fill")
                        }
                        .font(.footnote)
                    } else {
                        Button { guide.resetBandBluetooth() } label: {
                            Label("Reset Bluetooth & scan fresh", systemImage: "arrow.clockwise")
                        }
                        .font(.footnote)
                    }
                    Button("Disconnect the band from this iPhone", role: .destructive) { guide.disconnectBandFromPhone() }
                        .font(.footnote)
                    Text("Bluetooth stays connected when you unplug a charging cable, and reconnects by itself if the link drops.")
                        .font(.footnote).foregroundStyle(.secondary)
                } else {
                    Button { guide.connectBandFromPhone() } label: {
                        Label("Connect band (iPhone Bluetooth)", systemImage: "antenna.radiowaves.left.and.right")
                    }
                    .buttonStyle(.borderedProminent)
                    Text(guide.phoneOnly ? "iPhone-only mode: double-tap \(BandConfig.name) so it blinks blue, then tap Connect band."
                         : guide.bridgeWanted
                         ? "The laptop is waiting for this iPhone to carry the band. Double-tap \(BandConfig.name), then tap Connect band."
                         : "Double-tap \(BandConfig.name) so it blinks blue, then tap Connect band (starts iPhone-only mode automatically if no laptop is linked).")
                        .font(.footnote).foregroundStyle(.secondary)
                    Label("Tip: plug the band into this iPhone (USB-C) to charge it while you connect. Plugging in can wake it so it's findable for 60 s. Then unplug: the Bluetooth link stays. (iPhones can't use the band's USB data link, so the connection itself is Bluetooth.)",
                          systemImage: "cable.connector")
                        .font(.footnote).foregroundStyle(.secondary)
                }
            } header: { Text("Connection") }

            Section {
                if let pct = guide.battery {
                    HStack {
                        Text("Battery")
                        Spacer()
                        Text("\(pct)%").monospacedDigit().bold()
                    }
                    ProgressView(value: Double(pct), total: 100)
                        .tint(pct <= 15 ? .red : pct <= 35 ? .orange : .green)
                    Text([guide.batteryState, guide.batteryVolts.map { String(format: "%.2f V", $0) }]
                            .compactMap { $0 }.filter { !$0.isEmpty }.joined(separator: " · "))
                        .font(.footnote).foregroundStyle(.secondary)
                    if pct <= 15 && guide.batteryState != "charging" {
                        Text("Battery low: charge the band before the demo.").font(.footnote).foregroundStyle(.red)
                    }
                } else {
                    Text("Waiting for the band's battery reading…").foregroundStyle(.secondary)
                }
                if let t = guide.chipTemp { LabeledContent("Chip temperature", value: String(format: "%.0f °C", t)) }
            } header: { Text("Battery") }

            Section {
                LabeledContent("Status", value: guide.recording ? (guide.calibrated ? "recording" : "calibrating") : "idle")
                LabeledContent("Steps", value: "\(guide.steps)")
                LabeledContent("Distance", value: String(format: "%.1f m", Double(guide.steps) * guide.stepLength))
                LabeledContent("Facing now", value: String(format: "%.0f°", guide.facing))
                LabeledContent("Band state", value: guide.activity)
                LabeledContent("Gyro bias", value: String(format: "%.2f °/s", guide.gyroBias))
                LabeledContent("Band light", value: guide.ledState.replacingOccurrences(of: "_", with: " "))
                if guide.uncertain {
                    Text("Position uncertain: say \"I'm at the …\" at a saved place.").font(.footnote).foregroundStyle(.red)
                }
            } header: { Text("Tracking") }

            Section {
                Toggle("Buzz this iPhone", isOn: $guide.buzzing)
                ForEach(legend, id: \.cue) { item in
                    HStack {
                        Text(item.dots).font(.callout.monospaced()).foregroundStyle(.orange).frame(width: 70, alignment: .leading)
                        Text(item.text).font(.callout)
                        Spacer()
                        Button("Try") { guide.tryCue(item.cue) }.font(.caption).buttonStyle(.bordered)
                    }
                }
                Text(guide.haptics.supported
                     ? "Keep Wayback open (screen on): iPhones only play haptics for the app on screen."
                     : "This device has no haptic engine.")
                    .font(.footnote).foregroundStyle(.secondary)
            } header: { Text("Buzz patterns") }

            Section {
                ForEach(KeyStore.names, id: \.self) { name in
                    HStack {
                        Text(name.capitalized).frame(width: 90, alignment: .leading)
                        SecureField(KeyStore.get(name) == nil ? "paste key" : "saved ••••", text: Binding(
                            get: { keyText[name] ?? "" }, set: { keyText[name] = $0 }))
                            .textInputAutocapitalization(.never).autocorrectionDisabled()
                    }
                }
                Button("Save keys") {
                    for (name, v) in keyText where !v.isEmpty { KeyStore.set(name, v) }
                    keyText = [:]
                    savedNote = "Saved in this iPhone's Keychain."
                }
                Text(savedNote.isEmpty
                     ? "For iPhone-only mode: Deepgram (speech to text), Gemini (understanding), ElevenLabs (voice; optional, else the iPhone's voice). Kept in the Keychain, never shown or sent anywhere else."
                     : savedNote)
                    .font(.footnote).foregroundStyle(.secondary)
            } header: { Text("Keys (iPhone only)") }

            Section {
                Button(guide.phoneOnly ? "Stop iPhone-only mode" : "Disconnect from the laptop", role: .destructive) { guide.disconnect() }
            }
        }
    }
}
