import SwiftUI

struct ContentView: View {
    @StateObject private var guide = Guide()

    var body: some View {
        TabView {
            GuideView(guide: guide)
                .tabItem { Label("Guide", systemImage: "location.north.circle.fill") }
            MapView(guide: guide)
                .tabItem { Label("Map", systemImage: "map") }
            PlacesView(guide: guide)
                .tabItem { Label("Places", systemImage: "mappin.and.ellipse") }
            BandView(guide: guide)
                .tabItem { Label("Band", systemImage: "applewatch") }
        }
    }
}

/// The main screen: which way to go, what to do now, and Talk.
struct GuideView: View {
    @ObservedObject var guide: Guide
    @AppStorage("phoneLink") private var phoneLink = ""

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
        if guide.phoneOnly {
            return guide.bandConnectedOnPhone ? "\(BandConfig.name) connected" : "searching for \(BandConfig.name)…"
        }
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
                    if let pct = guide.battery {
                        Label("\(pct)%", systemImage: pct <= 15 ? "battery.25" : "battery.75")
                            .font(.caption).foregroundStyle(pct <= 15 ? .red : .secondary)
                    }
                    Text(linkText)
                        .font(.caption)
                        .padding(.horizontal, 10).padding(.vertical, 4)
                        .background(Capsule().fill(Color(.secondarySystemBackground)))
                        .foregroundStyle(guide.link == .on ? .green : .secondary)
                }

                if guide.link != .on {
                    Button { guide.startPhoneOnly() } label: {
                        Label("Use this iPhone only (no laptop)", systemImage: "iphone.radiowaves.left.and.right")
                            .frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.borderedProminent)
                    Text("The iPhone connects to \(BandConfig.name), tracks, guides, listens and speaks. Add your keys in the Band tab for voice.")
                        .font(.footnote).foregroundStyle(.secondary)
                    Text("Or use the laptop:").font(.footnote.bold()).frame(maxWidth: .infinity, alignment: .leading)
                    VStack(alignment: .leading, spacing: 8) {
                        Text("1. On the laptop: python3 main.py --band --phone  (or --bridge --phone to let this iPhone carry the band)")
                            .font(.footnote).foregroundStyle(.secondary)
                        Text("2. Paste the \"Phone (on the same Wi-Fi)\" link:").font(.footnote).foregroundStyle(.secondary)
                        TextField("http://192.168.…:8000/web/phone.html?ws_port=8765&token=…", text: $phoneLink, axis: .vertical)
                            .textInputAutocapitalization(.never)
                            .autocorrectionDisabled()
                            .font(.footnote.monospaced())
                            .padding(10)
                            .background(RoundedRectangle(cornerRadius: 10).fill(Color(.secondarySystemBackground)))
                        HStack {
                            Button {
                                if let pasted = UIPasteboard.general.string { phoneLink = pasted }
                            } label: { Label("Paste", systemImage: "doc.on.clipboard") }
                            Spacer()
                            Button { guide.connect(phoneLink: phoneLink) } label: { Text("Connect").bold() }
                                .buttonStyle(.borderedProminent)
                                .disabled(phoneLink.isEmpty)
                        }
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
                    Button { guide.talk() } label: {
                        Label("Talk", systemImage: "mic.fill").font(.title3.bold()).frame(maxWidth: .infinity).padding(.vertical, 6)
                    }
                    .buttonStyle(.borderedProminent)
                    Text("Or double-tap the band, speak, and double-tap again.")
                        .font(.footnote).foregroundStyle(.secondary)
                    if !guide.voice.isEmpty {
                        Text(guide.voice).font(.callout).multilineTextAlignment(.center)
                    }
                    HStack {
                        Label(guide.recording ? (guide.calibrated ? "Recording" : "Calibrating") : "Not recording",
                              systemImage: "figure.walk")
                        Spacer()
                        Text("\(guide.places.count) places")
                        Spacer()
                        Toggle("Buzz", isOn: $guide.buzzing).toggleStyle(.button)
                    }
                    .font(.footnote)
                    if !guide.bandStatus.isEmpty {
                        Label(guide.bandStatus, systemImage: "dot.radiowaves.left.and.right")
                            .font(.footnote).foregroundStyle(.secondary)
                    }
                }
            }
            .padding()
        }
    }
}

#Preview { ContentView() }
