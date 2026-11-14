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
                          systemImage: "dot.radiowaves.left.and.right")
                        .font(.footnote)
                    Button("Disconnect the band from this iPhone", role: .destructive) { guide.disconnectBandFromPhone() }
                        .font(.footnote)
                } else {
                    Button { guide.connectBandFromPhone() } label: {
                        Label("Connect band (iPhone Bluetooth)", systemImage: "antenna.radiowaves.left.and.right")
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(guide.link != .on)
                    Text(guide.bridgeWanted
                         ? "The laptop is waiting for this iPhone to carry the band. Double-tap the band, then connect."
                         : "To let this iPhone carry the band, run the laptop with: python3 main.py --bridge --phone")
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
                Button("Disconnect from the laptop", role: .destructive) { guide.disconnect() }
            }
        }
    }
}
