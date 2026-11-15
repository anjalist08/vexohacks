import SwiftUI

/// One screen. The map is the app; everything else floats cleanly on top of it.
/// Opens straight into iPhone-only mode: finds your Vexo band, fuses iPhone + band sensors,
/// guides with Core Haptics, listens via wrist mic, and logs live commands & events on screen.
struct ContentView: View {
    @StateObject private var guide = Guide()
    @State private var showSettings = false
    @State private var showSave = false
    @State private var showFeed = true
    @State private var feedExpanded = false
    @State private var micPulse = false
    @State private var mapZoom: CGFloat = 1.0
    @State private var mapPan: CGSize = .zero

    var previewMode: String? = nil

    private var bandConnected: Bool {
        guide.bandConnectedOnPhone || guide.bandStatus.contains("connected (") || guide.bandLinkStatus == "connected"
    }

    private var accent: Color {
        WaybackTheme.stateColor(for: guide.state)
    }

    private var topMapInset: CGFloat {
        (guide.guiding || guide.state == "done") ? 248 : 136
    }

    private var bottomMapInset: CGFloat {
        var h: CGFloat = 240
        if !guide.places.isEmpty || guide.trail.count > 3 { h += 50 }
        if showFeed && !guide.feed.isEmpty { h += feedExpanded ? 190 : 108 }
        return h
    }

    var body: some View {
        ZStack {
            TrailCanvas(
                guide: guide,
                topInset: topMapInset,
                bottomInset: bottomMapInset,
                zoom: $mapZoom,
                pan: $mapPan
            )
            .ignoresSafeArea()

            VStack(spacing: 10) {
                topBar

                if guide.guiding || guide.state == "done" {
                    guidanceCard
                        .transition(.move(edge: .top).combined(with: .opacity))
                }

                if abs(mapZoom - 1.0) > 0.05 || hypot(mapPan.width, mapPan.height) > 6 {
                    HStack {
                        Spacer()
                        Button {
                            withAnimation(.spring(response: 0.32, dampingFraction: 0.8)) {
                                mapZoom = 1.0
                                mapPan = .zero
                            }
                        } label: {
                            Label("Recenter", systemImage: "location.viewfinder")
                                .font(.caption.weight(.semibold))
                                .padding(.horizontal, 12)
                                .padding(.vertical, 7)
                                .floatingCapsule()
                        }
                        .tint(.primary)
                    }
                }

                Spacer(minLength: 0)

                if showFeed && !guide.feed.isEmpty {
                    liveActivityCard
                        .transition(.move(edge: .bottom).combined(with: .opacity))
                }

                if !guide.places.isEmpty || guide.trail.count > 3 {
                    placeChips
                }

                controls
            }
            .padding(.horizontal, 16)
            .padding(.bottom, 8)
            .animation(.spring(response: 0.32, dampingFraction: 0.84), value: guide.guiding)
            .animation(.spring(response: 0.32, dampingFraction: 0.84), value: guide.state)
            .animation(.spring(response: 0.3, dampingFraction: 0.86), value: showFeed)
            .animation(.spring(response: 0.3, dampingFraction: 0.86), value: feedExpanded)
        }
        .onAppear {
            if let mode = previewMode {
                loadDemo(guiding: mode == "guiding")
                return
            }
            if !guide.phoneOnly && guide.link == .off {
                guide.startPhoneOnly()
            }
            if ProcessInfo.processInfo.arguments.contains("-demo") {
                loadDemo(guiding: ProcessInfo.processInfo.arguments.contains("-guiding"))
            }
        }
        .sheet(isPresented: $showSettings) {
            SettingsSheet(guide: guide)
        }
        .sheet(isPresented: $showSave) {
            SavePlaceSheet(guide: guide)
                .presentationDetents([.height(330), .medium])
                .presentationDragIndicator(.visible)
        }
    }

    // MARK: - Demo State (Simulator `-demo` / `-guiding` & Xcode Previews)

    private func loadDemo(guiding: Bool) {
        var pts: [TrailPoint] = []
        for i in 0...14 { pts.append(TrailPoint(x: 0, y: Double(i) * 0.7, jump: false)) }
        for i in 1...20 { pts.append(TrailPoint(x: -Double(i) * 0.7, y: 9.8, jump: false)) }
        for i in 1...9 { pts.append(TrailPoint(x: -14, y: 9.8 + Double(i) * 0.7, jump: false)) }
        guide.trail = pts
        guide.places = [
            Place(id: "a", label: "entrance", x: 0, y: 0, note: "Main lobby doors", floor: nil),
            Place(id: "b", label: "elevator", x: -7, y: 9.8, note: nil, floor: "1"),
        ]
        guide.position = CGPoint(x: -14, y: 16.1)
        guide.facing = 0
        guide.steps = 44
        guide.recording = true
        guide.calibrated = true
        guide.bandName = BandConfig.name
        guide.bandStatus = "\(BandConfig.name) connected (iPhone Bluetooth)"
        guide.bandLinkStatus = "connected"
        guide.battery = 82
        guide.trackSource = "iPhone + band"
        guide.noteBandLinkTransition("connected")
        guide.logHeard("start route", viaSpeech: true)
        guide.logAction("Started route", detail: "Fused sensors active", icon: "play.circle.fill", tint: "green")
        guide.logHeard("remember this as elevator", viaSpeech: true)
        guide.logAction("Added landmark: Elevator", detail: "Floor +1", icon: "mappin.circle.fill", tint: "purple")
        if guiding {
            guide.guiding = true
            guide.guideTarget = "entrance"
            guide.state = "on"
            guide.big = "Walk 9 steps"
            guide.sub = "then turn left · to the entrance"
            guide.waypoints = [
                CGPoint(x: -14, y: 16.1),
                CGPoint(x: -14, y: 9.8),
                CGPoint(x: 0, y: 9.8),
                CGPoint(x: 0, y: 0),
            ]
            guide.logHeard("take me back to the entrance", viaSpeech: true)
            guide.logAction("Guiding to entrance", detail: "Walk 9 steps, then turn left", icon: "figure.walk.circle.fill", tint: "cyan")
            guide.logBuzz("on_track")
        }
    }

    // MARK: - Top Bar: Brand + Band Status + Activity Toggle + Settings

    private var topBar: some View {
        HStack(spacing: 8) {
            Button {
                if bandConnected {
                    guide.flashBand()
                } else {
                    guide.resetBandBluetooth()
                }
            } label: {
                HStack(spacing: 9) {
                    WaybackLogoMark(size: 28)

                    VStack(alignment: .leading, spacing: 1) {
                        HStack(spacing: 6) {
                            Circle()
                                .fill(bandConnected ? Color.green : Color.orange)
                                .frame(width: 7.5, height: 7.5)
                            Text(bandConnected ? guide.bandName : (guide.bandStatus.isEmpty ? "Scanning for \(BandConfig.name)…" : guide.bandStatus))
                                .font(.footnote.weight(.semibold))
                                .lineLimit(1)
                        }
                        if bandConnected && !guide.trackSource.isEmpty {
                            Text(guide.level == 0
                                 ? guide.trackSource
                                 : "\(guide.trackSource) · floor \(guide.level > 0 ? "+" : "")\(guide.level)")
                                .font(.system(size: 10, weight: .medium))
                                .foregroundStyle(.secondary)
                                .lineLimit(1)
                        }
                    }

                    if let pct = guide.battery, bandConnected {
                        HStack(spacing: 3) {
                            Image(systemName: pct <= 15 ? "battery.25" : pct <= 50 ? "battery.50" : "battery.100")
                            Text("\(pct)%").monospacedDigit()
                        }
                        .font(.caption2.weight(.semibold))
                        .foregroundStyle(pct <= 15 ? .red : .secondary)
                        .padding(.horizontal, 7)
                        .padding(.vertical, 3)
                        .background(Capsule().fill(Color.primary.opacity(0.06)))
                    }
                }
                .padding(.leading, 8)
                .padding(.trailing, 13)
                .padding(.vertical, 7)
                .floatingCapsule()
            }
            .buttonStyle(.plain)
            .accessibilityLabel(bandConnected ? "\(guide.bandName) connected. Tap to flash band light." : "Tap to scan for \(BandConfig.name)")

            Spacer(minLength: 4)

            if !guide.feed.isEmpty {
                Button {
                    showFeed.toggle()
                } label: {
                    ZStack(alignment: .topTrailing) {
                        Image(systemName: showFeed ? "list.bullet.below.rectangle" : "list.bullet")
                            .font(.subheadline.weight(.semibold))
                            .frame(width: 40, height: 40)
                            .floatingCapsule()

                        if !showFeed {
                            Circle()
                                .fill(WaybackTheme.brand)
                                .frame(width: 8, height: 8)
                                .offset(x: -2, y: 2)
                        }
                    }
                }
                .tint(.primary)
                .accessibilityLabel(showFeed ? "Hide live activity" : "Show live activity")
            }

            Button {
                showSettings = true
            } label: {
                Image(systemName: "gearshape.fill")
                    .font(.subheadline.weight(.semibold))
                    .frame(width: 40, height: 40)
                    .floatingCapsule()
            }
            .tint(.primary)
            .accessibilityLabel("Settings")
        }
    }

    // MARK: - Active Guidance Banner Card

    private var guidanceCard: some View {
        HStack(spacing: 14) {
            ZStack {
                Circle()
                    .fill(accent.opacity(0.16))
                    .frame(width: 58, height: 58)
                Circle()
                    .strokeBorder(accent.opacity(0.35), lineWidth: 1.5)
                    .frame(width: 58, height: 58)
                Image(systemName: guide.state == "done" ? "checkmark.seal.fill" : "location.north.fill")
                    .font(.system(size: 26, weight: .bold))
                    .foregroundStyle(accent.gradient)
                    .rotationEffect(.degrees(guide.state == "done" ? 0 : guide.arrowDegrees))
                    .animation(.spring(response: 0.28, dampingFraction: 0.78), value: guide.arrowDegrees)
            }

            VStack(alignment: .leading, spacing: 3) {
                HStack(spacing: 6) {
                    Text(guide.state == "done" ? "ARRIVED" : (guide.state == "wrong" ? "ADJUST HEADING" : "GUIDING"))
                        .font(.system(size: 10, weight: .bold, design: .rounded))
                        .tracking(0.6)
                        .foregroundStyle(accent)
                    if !guide.guideTarget.isEmpty && guide.state != "done" {
                        Text("· \(guide.guideTarget)")
                            .font(.caption2.weight(.semibold))
                            .foregroundStyle(.secondary)
                            .lineLimit(1)
                    }
                }
                Text(guide.big)
                    .font(.system(.title3, design: .rounded).weight(.bold))
                    .lineLimit(2)
                if !guide.sub.isEmpty {
                    Text(guide.sub)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .lineLimit(2)
                }
            }

            Spacer(minLength: 0)

            Button {
                guide.buzzing.toggle()
            } label: {
                Image(systemName: guide.buzzing ? "iphone.radiowaves.left.and.right" : "iphone.slash")
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(guide.buzzing ? accent : .secondary)
                    .frame(width: 36, height: 36)
                    .background(Circle().fill(Color.primary.opacity(0.06)))
            }
            .buttonStyle(.plain)
            .accessibilityLabel(guide.buzzing ? "Mute directional vibration" : "Enable directional vibration")
        }
        .padding(14)
        .floatingCard(cornerRadius: 24)
    }

    // MARK: - Live Activity & Command Feed (Compact + Expandable on Home)

    private static let feedClock: DateFormatter = {
        let f = DateFormatter()
        f.dateFormat = "HH:mm:ss"
        return f
    }()

    private func feedTint(_ name: String) -> Color {
        switch name {
        case "blue": return .blue
        case "green": return .green
        case "purple": return WaybackTheme.landmarkColor
        case "cyan": return .cyan
        case "indigo": return .indigo
        case "orange": return .orange
        case "red": return .red
        default: return .secondary
        }
    }

    private func feedBadge(_ kind: FeedItem.Kind) -> String {
        switch kind {
        case .heard: return "YOU"
        case .action: return "WAYBACK"
        case .buzz: return "BUZZ"
        case .band: return "VEXO"
        }
    }

    private var liveActivityCard: some View {
        let visibleItems = Array(guide.feed.prefix(feedExpanded ? 18 : 2))
        return VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 6) {
                Image(systemName: "waveform.and.magnifyingglass")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.secondary)
                Text("Live Activity")
                    .font(.caption.weight(.bold))
                    .foregroundStyle(.secondary)

                Text("\(guide.feed.count)")
                    .font(.system(size: 10, weight: .bold, design: .rounded).monospacedDigit())
                    .padding(.horizontal, 6)
                    .padding(.vertical, 1.5)
                    .background(Capsule().fill(Color.primary.opacity(0.08)))
                    .foregroundStyle(.secondary)

                Spacer()

                if guide.feed.count > 2 {
                    Button {
                        feedExpanded.toggle()
                    } label: {
                        HStack(spacing: 3) {
                            Text(feedExpanded ? "Compact" : "All")
                            Image(systemName: feedExpanded ? "chevron.down" : "chevron.up")
                        }
                        .font(.caption2.weight(.semibold))
                        .foregroundStyle(.secondary)
                    }
                    .buttonStyle(.plain)
                }

                Button("Clear") {
                    guide.clearFeed()
                }
                .font(.caption2.weight(.semibold))
                .foregroundStyle(.tertiary)
                .padding(.leading, 4)
            }

            if feedExpanded {
                ScrollView(showsIndicators: true) {
                    VStack(spacing: 6) {
                        ForEach(visibleItems) { item in
                            feedRow(item)
                        }
                    }
                }
                .frame(maxHeight: 156)
            } else {
                VStack(spacing: 6) {
                    ForEach(visibleItems) { item in
                        feedRow(item)
                    }
                }
            }
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 11)
        .floatingCard(cornerRadius: WaybackTheme.compactCornerRadius)
    }

    private func feedRow(_ item: FeedItem) -> some View {
        let color = feedTint(item.tint)
        return HStack(alignment: .center, spacing: 9) {
            ZStack {
                RoundedRectangle(cornerRadius: 7, style: .continuous)
                    .fill(color.opacity(0.15))
                    .frame(width: 24, height: 24)
                Image(systemName: item.icon)
                    .font(.system(size: 11, weight: .semibold))
                    .foregroundStyle(color)
            }

            Text(feedBadge(item.kind))
                .font(.system(size: 9, weight: .bold, design: .rounded))
                .tracking(0.4)
                .padding(.horizontal, 5)
                .padding(.vertical, 1.5)
                .background(Capsule().fill(color.opacity(0.13)))
                .foregroundStyle(color)

            VStack(alignment: .leading, spacing: 1) {
                Text(item.title)
                    .font(.caption.weight(.medium))
                    .foregroundStyle(.primary)
                    .lineLimit(feedExpanded ? 2 : 1)
                if feedExpanded, let detail = item.detail, !detail.isEmpty {
                    Text(detail)
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                }
            }

            Spacer(minLength: 4)

            Text(Self.feedClock.string(from: item.time))
                .font(.system(size: 10).monospacedDigit())
                .foregroundStyle(.tertiary)
        }
    }

    // MARK: - Saved Place Chips (1-Tap Navigation)

    private var placeChips: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 8) {
                chip("Back to start", "arrow.uturn.backward", tint: WaybackTheme.guideColor) {
                    guide.command("take me back to the start")
                }
                ForEach(guide.places) { place in
                    let floorSuffix: String = {
                        guard let f = place.floor, !f.isEmpty, f != "0" else { return "" }
                        return f.hasPrefix("-") ? " (\(f)F)" : " (+\(f)F)"
                    }()
                    chip("\(place.label.capitalized)\(floorSuffix)", "mappin.circle.fill", tint: WaybackTheme.landmarkColor) {
                        guide.command("take me to the \(place.label)")
                    }
                }
            }
            .padding(.horizontal, 2)
        }
    }

    private func chip(_ title: String, _ icon: String, tint: Color, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            HStack(spacing: 6) {
                Image(systemName: icon)
                    .foregroundStyle(tint)
                Text(title)
                    .foregroundStyle(.primary)
            }
            .font(.subheadline.weight(.medium))
            .padding(.horizontal, 13)
            .padding(.vertical, 8.5)
            .floatingCapsule()
        }
        .buttonStyle(.plain)
    }

    // MARK: - Floating Bottom Control Dock

    private var controls: some View {
        let listening = guide.voiceEngine.listening
        return VStack(spacing: 13) {
            HStack(spacing: 6) {
                if listening {
                    Image(systemName: "waveform")
                        .font(.caption.weight(.bold))
                        .foregroundStyle(.indigo)
                } else if guide.recording {
                    Circle()
                        .fill(guide.calibrated ? Color.green : Color.orange)
                        .frame(width: 6.5, height: 6.5)
                }
                Text(statusLine)
                    .font(.footnote.weight(.medium))
                    .foregroundStyle(listening ? .primary : .secondary)
                    .multilineTextAlignment(.center)
                    .lineLimit(2)
            }
            .frame(maxWidth: .infinity)

            HStack {
                dockSideButton(
                    title: guide.recording ? "Stop" : "Start route",
                    subtitle: guide.recording ? "\(guide.steps) steps" : nil,
                    icon: guide.recording ? "stop.fill" : "figure.walk",
                    tint: guide.recording ? .red : WaybackTheme.routeColor
                ) {
                    guide.command(guide.recording ? "stop route" : "start route")
                }

                Spacer()

                // Hero Talk / Wrist-Mic Button
                Button {
                    guide.talk()
                } label: {
                    ZStack {
                        if listening {
                            Circle()
                                .stroke(Color.indigo.opacity(0.35), lineWidth: 3)
                                .frame(width: 92, height: 92)
                                .scaleEffect(micPulse ? 1.14 : 0.96)
                                .opacity(micPulse ? 0.0 : 0.85)
                                .onAppear {
                                    withAnimation(.easeOut(duration: 1.15).repeatForever(autoreverses: false)) {
                                        micPulse = true
                                    }
                                }
                                .onDisappear { micPulse = false }
                        }

                        Circle()
                            .fill(
                                LinearGradient(
                                    colors: listening
                                        ? [Color.indigo, Color.purple]
                                        : [Color(red: 0.06, green: 0.52, blue: 0.98), Color(red: 0.0, green: 0.68, blue: 0.92)],
                                    startPoint: .topLeading,
                                    endPoint: .bottomTrailing
                                )
                            )
                            .frame(width: 78, height: 78)
                            .shadow(color: (listening ? Color.indigo : Color.cyan).opacity(0.34), radius: 12, y: 6)

                        Image(systemName: listening ? "waveform" : "mic.fill")
                            .font(.system(size: 28, weight: .semibold))
                            .foregroundStyle(.white)
                    }
                }
                .buttonStyle(.plain)
                .accessibilityLabel(listening ? "Stop listening" : "Talk")

                Spacer()

                dockSideButton(
                    title: "Save place",
                    subtitle: guide.places.isEmpty ? nil : "\(guide.places.count) saved",
                    icon: "mappin.and.ellipse",
                    tint: WaybackTheme.landmarkColor
                ) {
                    showSave = true
                }
                .disabled(!guide.recording)
                .opacity(guide.recording ? 1 : 0.42)
            }
        }
        .padding(.horizontal, 20)
        .padding(.top, 14)
        .padding(.bottom, 16)
        .floatingCard(cornerRadius: WaybackTheme.dockCornerRadius)
    }

    private var statusLine: String {
        if !guide.voice.isEmpty { return guide.voice }
        if guide.recording && !guide.calibrated { return "Hold your arm still for a moment…" }
        if guide.recording {
            let floor = guide.level == 0 ? "" : " · floor \(guide.level > 0 ? "+" : "")\(guide.level)"
            return "Recording · \(guide.steps) steps\(floor) — double-tap band to name a spot"
        }
        if !bandConnected { return "Double-tap \(BandConfig.name) so its blue light blinks" }
        return "Tap Start route, or double-tap the band and say \u{201C}start route\u{201D}"
    }

    private func dockSideButton(
        title: String,
        subtitle: String?,
        icon: String,
        tint: Color,
        action: @escaping () -> Void
    ) -> some View {
        Button(action: action) {
            VStack(spacing: 5) {
                Image(systemName: icon)
                    .font(.title3.weight(.semibold))
                    .foregroundStyle(tint)
                    .frame(width: 50, height: 50)
                    .background(Circle().fill(tint.opacity(0.14)))
                Text(title)
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.primary)
                if let subtitle {
                    Text(subtitle)
                        .font(.system(size: 10).monospacedDigit())
                        .foregroundStyle(.secondary)
                }
            }
            .frame(width: 88)
        }
        .buttonStyle(.plain)
    }
}

// MARK: - Quick Save Landmark Sheet (1-Tap Presets + Custom Name)

struct SavePlaceSheet: View {
    @ObservedObject var guide: Guide
    @Environment(\.dismiss) private var dismiss
    @State private var customName = ""
    @State private var customNote = ""

    private func pin(_ label: String, note: String? = nil) {
        let trimmed = label.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }
        if guide.phoneOnly {
            guide.logHeard("remember this as \(trimmed)", viaSpeech: false)
            let cleanNote = note?.trimmingCharacters(in: .whitespacesAndNewlines)
            guide.brain.run(.remember(trimmed, (cleanNote?.isEmpty == false) ? cleanNote : nil))
        } else {
            guide.command("remember this as the \(trimmed)")
        }
        dismiss()
    }

    var body: some View {
        NavigationStack {
            VStack(alignment: .leading, spacing: 18) {
                Text("One-Tap Presets")
                    .font(.caption.weight(.bold))
                    .foregroundStyle(.secondary)

                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 9) {
                        ForEach(WaybackTheme.quickPlacePresets, id: \.label) { preset in
                            Button {
                                pin(preset.label)
                            } label: {
                                Label(preset.label.capitalized, systemImage: preset.icon)
                                    .font(.subheadline.weight(.semibold))
                                    .padding(.horizontal, 13)
                                    .padding(.vertical, 9)
                                    .background(
                                        Capsule()
                                            .fill(WaybackTheme.landmarkColor.opacity(0.13))
                                    )
                                    .foregroundStyle(WaybackTheme.landmarkColor)
                            }
                            .buttonStyle(.plain)
                        }
                    }
                }

                Divider()

                VStack(alignment: .leading, spacing: 10) {
                    Text("Or Custom Name")
                        .font(.caption.weight(.bold))
                        .foregroundStyle(.secondary)

                    TextField("e.g. coffee bar, room 204…", text: $customName)
                        .textInputAutocapitalization(.never)
                        .padding(11)
                        .background(RoundedRectangle(cornerRadius: 12).fill(Color(.secondarySystemBackground)))
                        .submitLabel(.done)
                        .onSubmit { pin(customName, note: customNote) }

                    TextField("Optional note (e.g. near water cooler)", text: $customNote)
                        .font(.subheadline)
                        .padding(11)
                        .background(RoundedRectangle(cornerRadius: 12).fill(Color(.secondarySystemBackground)))
                }

                Button {
                    pin(customName, note: customNote)
                } label: {
                    Label("Pin Current Spot", systemImage: "mappin.and.ellipse")
                        .font(.headline)
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 6)
                }
                .buttonStyle(.borderedProminent)
                .tint(WaybackTheme.landmarkColor)
                .disabled(customName.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)

                Spacer(minLength: 0)
            }
            .padding(20)
            .navigationTitle("Save Place")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }
                }
            }
        }
    }
}

// MARK: - Interactive Full-Screen Spatial Map Canvas

/// Full-screen route map: your walk (blue), active guidance path (dashed green), landmarks, start, and live heading cone.
/// Supports pinch-to-zoom and drag-to-pan; +y is the direction faced at "start route".
struct TrailCanvas: View {
    @ObservedObject var guide: Guide
    var topInset: CGFloat = 140
    var bottomInset: CGFloat = 300
    @Binding var zoom: CGFloat
    @Binding var pan: CGSize

    @Environment(\.colorScheme) private var colorScheme
    @GestureState private var pinchDelta: CGFloat = 1.0
    @GestureState private var dragDelta: CGSize = .zero

    private var effectiveZoom: CGFloat {
        min(max(zoom * pinchDelta, 0.5), 5.0)
    }

    private var effectivePan: CGSize {
        CGSize(width: pan.width + dragDelta.width, height: pan.height + dragDelta.height)
    }

    var body: some View {
        Canvas { ctx, size in draw(ctx, size) }
            .background(Color(.systemGroupedBackground))
            .contentShape(Rectangle())
            .gesture(
                SimultaneousGesture(
                    MagnificationGesture()
                        .updating($pinchDelta) { value, state, _ in state = value }
                        .onEnded { value in zoom = min(max(zoom * value, 0.5), 5.0) },
                    DragGesture()
                        .updating($dragDelta) { value, state, _ in state = value.translation }
                        .onEnded { value in
                            pan = CGSize(
                                width: pan.width + value.translation.width,
                                height: pan.height + value.translation.height
                            )
                        }
                )
            )
            .accessibilityLabel("Map of your route with \(guide.places.count) saved places")
    }

    private func draw(_ ctx: GraphicsContext, _ size: CGSize) {
        let casingColor: Color = colorScheme == .dark ? Color(.systemBackground) : .white

        var xs = guide.trail.map(\.x) + guide.backTrail.map(\.x) + guide.places.map(\.x)
            + guide.waypoints.map { Double($0.x) } + [Double(guide.position.x), 0]
        var ys = guide.trail.map(\.y) + guide.backTrail.map(\.y) + guide.places.map(\.y)
            + guide.waypoints.map { Double($0.y) } + [Double(guide.position.y), 0]
        xs.append(0); ys.append(0)
        let minX = xs.min() ?? 0, maxX = xs.max() ?? 0, minY = ys.min() ?? 0, maxY = ys.max() ?? 0

        let area = CGRect(
            x: 52,
            y: topInset,
            width: max(size.width - 104, 50),
            height: max(size.height - topInset - bottomInset, 60)
        )
        let baseScale = min(area.width / max(maxX - minX, 6), area.height / max(maxY - minY, 6))
        let scale = baseScale * effectiveZoom
        let cx = (minX + maxX) / 2, cy = (minY + maxY) / 2
        let mid = CGPoint(x: area.midX + effectivePan.width, y: area.midY + effectivePan.height)

        func pt(_ x: Double, _ y: Double) -> CGPoint {
            CGPoint(x: mid.x + (x - cx) * scale, y: mid.y - (y - cy) * scale)
        }

        // Subtle 5 m coordinate grid
        var grid = Path()
        let cell = max(5 * scale, 18)
        var gx = mid.x.truncatingRemainder(dividingBy: cell)
        if gx < 0 { gx += cell }
        while gx < size.width {
            grid.move(to: CGPoint(x: gx, y: 0))
            grid.addLine(to: CGPoint(x: gx, y: size.height))
            gx += cell
        }
        var gy = mid.y.truncatingRemainder(dividingBy: cell)
        if gy < 0 { gy += cell }
        while gy < size.height {
            grid.move(to: CGPoint(x: 0, y: gy))
            grid.addLine(to: CGPoint(x: size.width, y: gy))
            gy += cell
        }
        ctx.stroke(grid, with: .color(.primary.opacity(colorScheme == .dark ? 0.07 : 0.045)), lineWidth: 1)

        func line(_ pts: [TrailPoint], _ color: Color, _ width: CGFloat, halo: Bool = false) {
            guard pts.count > 1 else { return }
            var path = Path()
            for (i, p) in pts.enumerated() {
                if i == 0 || p.jump { path.move(to: pt(p.x, p.y)) } else { path.addLine(to: pt(p.x, p.y)) }
            }
            if halo {
                ctx.stroke(path, with: .color(color.opacity(0.14)),
                           style: StrokeStyle(lineWidth: width + 12, lineCap: .round, lineJoin: .round))
            }
            ctx.stroke(path, with: .color(casingColor),
                       style: StrokeStyle(lineWidth: width + 4.5, lineCap: .round, lineJoin: .round))
            ctx.stroke(path, with: .color(color),
                       style: StrokeStyle(lineWidth: width, lineCap: .round, lineJoin: .round))
        }

        let guidingNow = guide.waypoints.count > 1
        line(guide.trail, guidingNow ? Color(.systemGray3) : WaybackTheme.routeColor, 6, halo: !guidingNow)

        if guidingNow {
            var w = Path()
            w.move(to: pt(guide.waypoints[0].x, guide.waypoints[0].y))
            for p in guide.waypoints.dropFirst() { w.addLine(to: pt(p.x, p.y)) }
            ctx.stroke(w, with: .color(WaybackTheme.guideColor.opacity(0.18)),
                       style: StrokeStyle(lineWidth: 14, lineCap: .round, lineJoin: .round))
            ctx.stroke(w, with: .color(WaybackTheme.guideColor),
                       style: StrokeStyle(lineWidth: 5.5, lineCap: .round, lineJoin: .round, dash: [2, 11]))
        }

        line(guide.backTrail, WaybackTheme.guideColor, 6, halo: true)

        func dot(_ p: CGPoint, _ r: CGFloat, _ color: Color) {
            ctx.fill(Path(ellipseIn: CGRect(x: p.x - r - 3, y: p.y - r - 3, width: 2 * r + 6, height: 2 * r + 6)),
                     with: .color(casingColor))
            ctx.fill(Path(ellipseIn: CGRect(x: p.x - r, y: p.y - r, width: 2 * r, height: 2 * r)),
                     with: .color(color))
        }

        if guide.trail.count > 1 || guide.recording {
            let s = pt(0, 0)
            dot(s, 6, .gray)
            let placeAtStart = guide.places.contains { abs($0.x) < 1.5 && abs($0.y) < 1.5 }
            if !placeAtStart {
                ctx.draw(
                    Text("Start").font(.caption2.weight(.semibold)).foregroundColor(.secondary),
                    at: CGPoint(x: s.x, y: s.y + 18)
                )
            }
        }

        for place in guide.places {
            let p = pt(place.x, place.y)
            dot(p, 7.5, WaybackTheme.landmarkColor)
            let floorText: String = {
                guard let f = place.floor, !f.isEmpty, f != "0" else { return "" }
                return f.hasPrefix("-") ? " · \(f)F" : " · +\(f)F"
            }()
            ctx.draw(
                Text("\(place.label.capitalized)\(floorText)")
                    .font(.caption.weight(.semibold))
                    .foregroundColor(.primary),
                at: CGPoint(x: p.x, y: p.y - 20)
            )
        }

        // User puck + live heading cone
        let me = pt(guide.position.x, guide.position.y)
        let a = guide.facing * .pi / 180
        func dir(_ da: Double, _ r: Double) -> CGPoint {
            CGPoint(x: me.x + sin(a + da) * r, y: me.y - cos(a + da) * r)
        }
        var cone = Path()
        cone.move(to: me)
        cone.addLine(to: dir(-0.48, 56))
        cone.addLine(to: dir(0, 64))
        cone.addLine(to: dir(0.48, 56))
        cone.closeSubpath()
        ctx.fill(cone, with: .color(WaybackTheme.routeColor.opacity(0.18)))

        ctx.fill(Path(ellipseIn: CGRect(x: me.x - 16, y: me.y - 16, width: 32, height: 32)),
                 with: .color(WaybackTheme.routeColor.opacity(0.14)))
        dot(me, 9, WaybackTheme.routeColor)
    }
}

// MARK: - Settings & Diagnostics Sheet

/// Everything not needed while actively walking: band number, voice keys, diagnostics, and optional laptop link.
struct SettingsSheet: View {
    @ObservedObject var guide: Guide
    @AppStorage("bandNumber") private var bandNumber = 80
    @AppStorage("phoneLink") private var phoneLink = ""
    @Environment(\.dismiss) private var dismiss
    @State private var showLaptopSetup = false

    private var targetBandName: String {
        String(format: "Vexo-HACK-%02d", bandNumber)
    }

    var body: some View {
        NavigationStack {
            List {
                // Brand & Status Summary
                Section {
                    HStack(spacing: 14) {
                        WaybackLogoMark(size: 48)
                        VStack(alignment: .leading, spacing: 3) {
                            Text("Wayback")
                                .font(.headline)
                            Text(guide.trackSource.isEmpty
                                 ? "Wearable Spatial Memory"
                                 : "Tracking via \(guide.trackSource)")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                            if let pct = guide.battery {
                                Text("\(guide.bandName) · \(pct)% battery")
                                    .font(.caption2)
                                    .foregroundStyle(.secondary)
                            }
                        }
                    }
                    .padding(.vertical, 4)
                }

                // Band Number & Bluetooth Controls
                Section {
                    HStack {
                        Label("Band Number", systemImage: "number.circle.fill")
                        Spacer()
                        TextField("80", value: $bandNumber, format: .number)
                            .keyboardType(.numberPad)
                            .multilineTextAlignment(.trailing)
                            .font(.body.monospacedDigit().weight(.semibold))
                            .frame(width: 80)
                    }

                    Button {
                        BandLink.forgetRemembered()
                        guide.disconnectBandFromPhone()
                        guide.connectBandFromPhone()
                        dismiss()
                    } label: {
                        Label("Connect to \(targetBandName)", systemImage: "dot.radiowaves.left.and.right")
                            .fontWeight(.semibold)
                    }

                    if guide.bandConnectedOnPhone {
                        Button {
                            guide.flashBand()
                        } label: {
                            Label("Flash Band Light", systemImage: "lightbulb.max.fill")
                        }
                    }
                } header: {
                    Text("Your Vexo Band")
                } footer: {
                    Text("Enter the number on your band's bag (default 80). Double-tap the band so its light blinks blue, then tap Connect.")
                }

                // Haptic Feedback
                Section("Guidance Feedback") {
                    Toggle(isOn: $guide.buzzing) {
                        Label("Vibrate for Directions", systemImage: "iphone.radiowaves.left.and.right")
                    }
                }

                // Detail Screens
                Section("Workspace & Tools") {
                    NavigationLink {
                        PlacesView(guide: guide)
                    } label: {
                        Label("Saved Places & Typed Commands", systemImage: "mappin.and.ellipse")
                    }

                    NavigationLink {
                        BandView(guide: guide)
                    } label: {
                        Label("Band Telemetry, API Keys & Haptics", systemImage: "wave.3.right.circle.fill")
                    }

                    NavigationLink {
                        MapView(guide: guide)
                    } label: {
                        Label("Full-Screen Map Inspector", systemImage: "map.fill")
                    }
                }

                // Optional Laptop Wi-Fi Bridge Mode
                Section {
                    DisclosureGroup("Link with Laptop over Wi-Fi (Optional)", isExpanded: $showLaptopSetup) {
                        VStack(alignment: .leading, spacing: 10) {
                            Text("Run `python3 main.py --band --phone` (or `--bridge --phone`) on your Mac, then paste the phone link:")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                                .padding(.top, 4)

                            TextField("http://192.168.…:8000/web/phone.html?ws_port=8765&token=…", text: $phoneLink, axis: .vertical)
                                .textInputAutocapitalization(.never)
                                .autocorrectionDisabled()
                                .font(.caption.monospaced())

                            HStack {
                                Button("Paste") {
                                    if let pasted = UIPasteboard.general.string { phoneLink = pasted }
                                }
                                .buttonStyle(.bordered)

                                Spacer()

                                if !guide.phoneOnly && guide.link == .on {
                                    Button("Switch to iPhone-Only", role: .destructive) {
                                        guide.disconnect()
                                        guide.startPhoneOnly()
                                    }
                                    .buttonStyle(.bordered)
                                } else {
                                    Button("Connect Wi-Fi") {
                                        guide.phoneOnly = false
                                        guide.connect(phoneLink: phoneLink)
                                        dismiss()
                                    }
                                    .buttonStyle(.borderedProminent)
                                    .disabled(phoneLink.isEmpty)
                                }
                            }
                        }
                        .padding(.vertical, 4)
                    }
                }
            }
            .navigationTitle("Settings")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Done") { dismiss() }
                        .fontWeight(.semibold)
                }
            }
        }
    }
}

// MARK: - Xcode Live Canvas Previews

#Preview("Home — Standby") {
    ContentView()
}

#Preview("Home — Demo Walk + Feed") {
    ContentView(previewMode: "demo")
}

#Preview("Home — Active Guidance") {
    ContentView(previewMode: "guiding")
}

#Preview("Settings Sheet") {
    SettingsSheet(guide: Guide())
}
