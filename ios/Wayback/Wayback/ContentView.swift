import SwiftUI

struct ContentView: View {
    @StateObject private var guide = Guide()
    @AppStorage("phoneLink") private var phoneLink = ""

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

    private var ringColor: Color {
        switch guide.state {
        case "on": return .green
        case "wrong": return .orange
        case "lost": return .red
        case "done": return .purple
        default: return .gray
        }
    }

    private var linkText: String {
        switch guide.link {
        case .off: return "not connected"
        case .connecting: return "connecting…"
        case .on: return "connected"
        case .failed(let why): return why
        }
    }

    var body: some View {
        ScrollView {
            VStack(spacing: 18) {
                HStack {
                    Text("Wayback").font(.title2.bold())
                    Spacer()
                    Text(linkText)
                        .font(.caption)
                        .padding(.horizontal, 10).padding(.vertical, 4)
                        .background(Capsule().fill(Color(.secondarySystemBackground)))
                        .foregroundStyle(guide.link == .on ? .green : .secondary)
                }

                if guide.link != .on {
                    VStack(alignment: .leading, spacing: 8) {
                        Text("Phone link").font(.caption).foregroundStyle(.secondary)
                        TextField("http://192.168.…:8000/web/phone.html?ws_port=8765&token=…", text: $phoneLink, axis: .vertical)
                            .textInputAutocapitalization(.never)
                            .autocorrectionDisabled()
                            .font(.footnote.monospaced())
                            .padding(10)
                            .background(RoundedRectangle(cornerRadius: 10).fill(Color(.secondarySystemBackground)))
                        Button {
                            if let pasted = UIPasteboard.general.string { phoneLink = pasted }
                        } label: { Label("Paste", systemImage: "doc.on.clipboard") }
                            .font(.footnote)
                    }
                }

                ZStack {
                    Circle().stroke(ringColor, lineWidth: 6).opacity(0.85)
                    Image(systemName: "arrowtriangle.up.fill")
                        .resizable().scaledToFit().frame(width: 80)
                        .foregroundStyle(guide.state == "on" ? .green : guide.state == "wrong" ? .orange : .secondary)
                        .rotationEffect(.degrees(guide.arrowDegrees))
                        .animation(.easeOut(duration: 0.2), value: guide.arrowDegrees)
                    Text("you face ↑").font(.caption2).foregroundStyle(.secondary).offset(y: -100)
                }
                .frame(width: 220, height: 220)
                .accessibilityHidden(true)

                Text(guide.big).font(.title.bold()).multilineTextAlignment(.center)
                Text(guide.sub).foregroundStyle(.secondary).multilineTextAlignment(.center)

                if guide.link == .on {
                    HStack(spacing: 12) {
                        Button { guide.talk() } label: {
                            Label("Talk", systemImage: "mic.fill").frame(maxWidth: .infinity)
                        }.buttonStyle(.borderedProminent)
                        Toggle(isOn: $guide.buzzing) { Text("Buzz") }.toggleStyle(.button)
                    }
                    Button("Disconnect", role: .destructive) { guide.disconnect() }.font(.footnote)
                } else {
                    Button { guide.connect(phoneLink: phoneLink) } label: {
                        Text("Connect").frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(phoneLink.isEmpty)
                }
                if !guide.bandStatus.isEmpty {
                    Label(guide.bandStatus, systemImage: "dot.radiowaves.left.and.right")
                        .font(.footnote).foregroundStyle(.secondary)
                }
                if !guide.voice.isEmpty {
                    Text(guide.voice).font(.callout).foregroundStyle(.secondary).multilineTextAlignment(.center)
                }

                VStack(alignment: .leading, spacing: 8) {
                    Text("BUZZ PATTERNS").font(.caption.bold()).foregroundStyle(.secondary)
                    ForEach(legend, id: \.cue) { item in
                        HStack {
                            Text(item.dots).font(.callout.monospaced()).foregroundStyle(.orange).frame(width: 70, alignment: .leading)
                            Text(item.text).font(.callout)
                            Spacer()
                            Button("Try") { guide.tryCue(item.cue) }.font(.caption).buttonStyle(.bordered)
                        }
                    }
                }
                .padding()
                .background(RoundedRectangle(cornerRadius: 16).fill(Color(.secondarySystemBackground)))

                Text(guide.haptics.supported
                     ? "Keep this app open (screen on): iPhones only play haptics for the app on screen."
                     : "This device has no haptic engine.")
                    .font(.footnote).foregroundStyle(.secondary).multilineTextAlignment(.center)
            }
            .padding()
        }
    }
}

#Preview { ContentView() }
