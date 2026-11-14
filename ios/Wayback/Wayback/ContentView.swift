import SwiftUI

/// One screen. The map is the app; everything else floats on it.
/// Opens straight into iPhone-only mode: finds the band, tracks, guides, listens and speaks here.
struct ContentView: View {
    @StateObject private var guide = Guide()
    @State private var showSettings = false
    @State private var showSave = false
    @State private var newPlace = ""

    private var bandConnected: Bool { guide.bandStatus.contains("connected (") }
    private var accent: Color {
        switch guide.state {
        case "on": return .green
        case "wrong": return .orange
        case "lost": return .red
        case "done": return .purple
        default: return .blue
        }
    }

    var body: some View {
        ZStack {
            TrailCanvas(guide: guide).ignoresSafeArea()

            VStack(spacing: 12) {
                topBar
                if guide.guiding || guide.state == "done" { guidanceCard }
                Spacer()
                if !guide.places.isEmpty { placeChips }
                controls
            }
            .padding(.horizontal, 16)
            .padding(.bottom, 8)
        }
        .onAppear { if !guide.phoneOnly { guide.startPhoneOnly() } }
        .sheet(isPresented: $showSettings) { SettingsSheet(guide: guide) }
        .alert("Name this place", isPresented: $showSave) {
            TextField("e.g. entrance", text: $newPlace)
            Button("Save") {
                let name = newPlace.trimmingCharacters(in: .whitespaces)
                if !name.isEmpty { guide.command("remember this as the \(name)") }
                newPlace = ""
            }
            Button("Cancel", role: .cancel) { newPlace = "" }
        }
    }

    // MARK: top: band status + settings

    private var topBar: some View {
        HStack(spacing: 8) {
            HStack(spacing: 8) {
                Circle().fill(bandConnected ? Color.green : Color.orange).frame(width: 9, height: 9)
                Text(bandConnected ? guide.bandName : (guide.bandStatus.isEmpty ? "Looking for your band…" : guide.bandStatus))
                    .font(.footnote.weight(.medium)).lineLimit(2)
                if let pct = guide.battery, bandConnected {
                    Text("\(pct)%").font(.footnote).foregroundStyle(.secondary)
                }
            }
            .padding(.horizontal, 14).padding(.vertical, 10)
            .background(.regularMaterial, in: Capsule())
            Spacer()
            Button { showSettings = true } label: {
                Image(systemName: "gearshape.fill").font(.body)
                    .padding(11).background(.regularMaterial, in: Circle())
            }
            .tint(.primary)
            .accessibilityLabel("Settings")
        }
    }

    // MARK: while being guided: which way, and what to do

    private var guidanceCard: some View {
        HStack(spacing: 16) {
            ZStack {
                Circle().fill(accent.opacity(0.18))
                Image(systemName: guide.state == "done" ? "checkmark" : "arrow.up")
                    .font(.system(size: 30, weight: .bold))
                    .foregroundStyle(accent)
                    .rotationEffect(.degrees(guide.state == "done" ? 0 : guide.arrowDegrees))
                    .animation(.easeOut(duration: 0.2), value: guide.arrowDegrees)
            }
            .frame(width: 64, height: 64)
            VStack(alignment: .leading, spacing: 2) {
                Text(guide.big).font(.title3.bold())
                if !guide.sub.isEmpty { Text(guide.sub).font(.subheadline).foregroundStyle(.secondary) }
            }
            Spacer(minLength: 0)
        }
        .padding(14)
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 22, style: .continuous))
    }

    // MARK: saved places: tap to be guided there

    private var placeChips: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 8) {
                chip("Start", "flag.fill") { guide.command("take me back to the start") }
                ForEach(guide.places) { place in
                    chip(place.label, "mappin") { guide.command("take me to the \(place.label)") }
                }
            }
        }
    }

    private func chip(_ title: String, _ icon: String, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Label(title, systemImage: icon).font(.subheadline.weight(.medium))
                .padding(.horizontal, 14).padding(.vertical, 9)
                .background(.regularMaterial, in: Capsule())
        }
        .tint(.primary)
    }

    // MARK: bottom: what it heard, and three buttons

    private var controls: some View {
        VStack(spacing: 14) {
            Text(statusLine)
                .font(.subheadline).foregroundStyle(.secondary)
                .multilineTextAlignment(.center).lineLimit(3)
                .frame(maxWidth: .infinity)

            HStack {
                side(guide.recording ? "Stop" : "Start", guide.recording ? "stop.fill" : "figure.walk",
                     tint: guide.recording ? .red : .blue) {
                    guide.command(guide.recording ? "stop route" : "start route")
                }
                Spacer()
                Button { guide.talk() } label: {
                    Image(systemName: "mic.fill").font(.system(size: 30, weight: .semibold))
                        .foregroundStyle(.white)
                        .frame(width: 84, height: 84)
                        .background(Circle().fill(Color.blue))
                        .shadow(color: .blue.opacity(0.35), radius: 12, y: 6)
                }
                .accessibilityLabel("Talk")
                Spacer()
                side("Save place", "mappin.and.ellipse", tint: .purple) { showSave = true }
                    .disabled(!guide.recording)
                    .opacity(guide.recording ? 1 : 0.4)
            }
        }
        .padding(.horizontal, 22).padding(.top, 16).padding(.bottom, 18)
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 30, style: .continuous))
    }

    private var statusLine: String {
        if !guide.voice.isEmpty { return guide.voice }
        if guide.recording && !guide.calibrated { return "Hold your arm still for a moment…" }
        if guide.recording { return "Recording · \(guide.steps) steps. Double-tap the band to name a place." }
        if !bandConnected { return "Double-tap your band so the iPhone can find it." }
        return "Tap Start, or double-tap the band and say \u{201C}start route\u{201D}."
    }

    private func side(_ title: String, _ icon: String, tint: Color, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            VStack(spacing: 6) {
                Image(systemName: icon).font(.title3.weight(.semibold))
                    .frame(width: 52, height: 52)
                    .background(Circle().fill(tint.opacity(0.15)))
                Text(title).font(.caption.weight(.medium))
            }
            .frame(width: 84)
        }
        .tint(tint)
    }
}

/// The route as a full-screen map: your walk (blue), the way back (dashed green), places, start, you.
/// +y is the way you faced at "start route".
struct TrailCanvas: View {
    @ObservedObject var guide: Guide

    var body: some View {
        Canvas { ctx, size in draw(ctx, size) }
            .background(Color(.systemGroupedBackground))
            .accessibilityLabel("Map of your route with \(guide.places.count) saved places")
    }

    private func draw(_ ctx: GraphicsContext, _ size: CGSize) {
        var xs = guide.trail.map(\.x) + guide.backTrail.map(\.x) + guide.places.map(\.x)
            + guide.waypoints.map { Double($0.x) } + [Double(guide.position.x), 0]
        var ys = guide.trail.map(\.y) + guide.backTrail.map(\.y) + guide.places.map(\.y)
            + guide.waypoints.map { Double($0.y) } + [Double(guide.position.y), 0]
        xs.append(0); ys.append(0)
        let minX = xs.min()!, maxX = xs.max()!, minY = ys.min()!, maxY = ys.max()!
        // Keep the route clear of the floating cards: use the middle band of the screen.
        let usable = CGSize(width: size.width - 60, height: size.height * 0.48)
        let scale = min(usable.width / max(maxX - minX, 8), usable.height / max(maxY - minY, 8))
        let cx = (minX + maxX) / 2, cy = (minY + maxY) / 2
        let mid = CGPoint(x: size.width / 2, y: size.height * 0.42)
        func pt(_ x: Double, _ y: Double) -> CGPoint {
            CGPoint(x: mid.x + (x - cx) * scale, y: mid.y - (y - cy) * scale)
        }

        // faint grid, 5 m squares
        var grid = Path()
        let cell = 5 * scale
        var gx = mid.x.truncatingRemainder(dividingBy: cell)
        while gx < size.width { grid.move(to: CGPoint(x: gx, y: 0)); grid.addLine(to: CGPoint(x: gx, y: size.height)); gx += cell }
        var gy = mid.y.truncatingRemainder(dividingBy: cell)
        while gy < size.height { grid.move(to: CGPoint(x: 0, y: gy)); grid.addLine(to: CGPoint(x: size.width, y: gy)); gy += cell }
        ctx.stroke(grid, with: .color(.primary.opacity(0.05)), lineWidth: 1)

        func line(_ pts: [TrailPoint], _ color: Color, _ width: CGFloat) {
            guard pts.count > 1 else { return }
            var path = Path()
            for (i, p) in pts.enumerated() {
                if i == 0 || p.jump { path.move(to: pt(p.x, p.y)) } else { path.addLine(to: pt(p.x, p.y)) }
            }
            let style = StrokeStyle(lineWidth: width, lineCap: .round, lineJoin: .round)
            ctx.stroke(path, with: .color(.white), style: StrokeStyle(lineWidth: width + 5, lineCap: .round, lineJoin: .round))
            ctx.stroke(path, with: .color(color), style: style)
        }
        line(guide.trail, .blue, 6)
        if guide.waypoints.count > 1 {
            var w = Path()
            w.move(to: pt(guide.waypoints[0].x, guide.waypoints[0].y))
            for p in guide.waypoints.dropFirst() { w.addLine(to: pt(p.x, p.y)) }
            ctx.stroke(w, with: .color(.green), style: StrokeStyle(lineWidth: 5, lineCap: .round, lineJoin: .round, dash: [2, 10]))
        }
        line(guide.backTrail, .green, 5)

        func dot(_ p: CGPoint, _ r: CGFloat, _ color: Color) {
            ctx.fill(Path(ellipseIn: CGRect(x: p.x - r - 3, y: p.y - r - 3, width: 2 * r + 6, height: 2 * r + 6)), with: .color(.white))
            ctx.fill(Path(ellipseIn: CGRect(x: p.x - r, y: p.y - r, width: 2 * r, height: 2 * r)), with: .color(color))
        }
        if guide.trail.count > 1 || guide.recording {
            let s = pt(0, 0)
            dot(s, 6, .gray)
            ctx.draw(Text("Start").font(.caption2.weight(.semibold)).foregroundColor(.secondary), at: CGPoint(x: s.x, y: s.y + 18))
        }
        for place in guide.places {
            let p = pt(place.x, place.y)
            dot(p, 7, .purple)
            ctx.draw(Text(place.label).font(.caption.weight(.semibold)), at: CGPoint(x: p.x, y: p.y - 20))
        }

        // you: a dot and the way you face
        let me = pt(guide.position.x, guide.position.y)
        let a = guide.facing * .pi / 180
        func dir(_ da: Double, _ r: Double) -> CGPoint { CGPoint(x: me.x + sin(a + da) * r, y: me.y - cos(a + da) * r) }
        var cone = Path()
        cone.move(to: me); cone.addLine(to: dir(-0.5, 60)); cone.addLine(to: dir(0, 66)); cone.addLine(to: dir(0.5, 60)); cone.closeSubpath()
        ctx.fill(cone, with: .color(.blue.opacity(0.16)))
        dot(me, 9, .blue)
    }
}

/// Everything that is not needed while walking: band number, voice keys, the old detail screens.
struct SettingsSheet: View {
    @ObservedObject var guide: Guide
    @AppStorage("bandNumber") private var bandNumber = 80
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            List {
                Section {
                    HStack {
                        Text("Band number")
                        Spacer()
                        TextField("80", value: $bandNumber, format: .number)
                            .keyboardType(.numberPad).multilineTextAlignment(.trailing).frame(width: 80)
                    }
                    Button("Connect to Vexo-HACK-\(String(format: "%02d", bandNumber))") {
                        UserDefaults.standard.removeObject(forKey: "waybackBandIdentifier")   // forget the old band
                        guide.disconnectBandFromPhone()
                        guide.connectBandFromPhone()
                        dismiss()
                    }
                } header: { Text("Your band") } footer: {
                    Text("The number on your band's bag. Double-tap the band, then reconnect.")
                }
                Section("Feedback") {
                    Toggle("Vibrate for directions", isOn: $guide.buzzing)
                }
                Section("More") {
                    NavigationLink("Places and typed commands") { PlacesView(guide: guide) }
                    NavigationLink("Band details, voice keys, haptics test") { BandView(guide: guide) }
                }
            }
            .navigationTitle("Settings")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } } }
        }
    }
}

#Preview { ContentView() }
