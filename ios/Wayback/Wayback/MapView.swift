import SwiftUI

/// Interactive 2D route map with pinch-zoom, drag-pan, floating telemetry HUD, and place badges.
/// +y is the direction you faced at "start route".
struct MapView: View {
    @ObservedObject var guide: Guide

    @State private var zoom: CGFloat = 1.0
    @State private var lastZoom: CGFloat = 1.0
    @State private var pan: CGSize = .zero
    @State private var lastPan: CGSize = .zero

    private var distanceMeters: Double {
        Double(guide.steps) * guide.stepLength
    }

    var body: some View {
        VStack(spacing: 12) {
            // Header bar
            HStack(spacing: 10) {
                WaybackLogoMark(size: 32)
                VStack(alignment: .leading, spacing: 1) {
                    Text("Spatial Trail")
                        .font(.system(.title3, design: .rounded).weight(.bold))
                    Text(guide.guiding ? "Guiding to \(guide.guideTarget)" : "Metric indoor path (+y = start heading)")
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                }
                Spacer()
                if !guide.mode.isEmpty && guide.mode != "LIVE" {
                    Text(guide.mode)
                        .font(.caption2.weight(.bold))
                        .padding(.horizontal, 8)
                        .padding(.vertical, 4)
                        .background(Capsule().fill(Color.orange.opacity(0.18)))
                        .foregroundStyle(.orange)
                }
            }

            // Map Canvas with HUD overlays & gestures
            ZStack {
                Canvas { ctx, size in
                    draw(ctx, size)
                }
                .background(
                    RoundedRectangle(cornerRadius: 22, style: .continuous)
                        .fill(Color(.secondarySystemGroupedBackground))
                )
                .clipShape(RoundedRectangle(cornerRadius: 22, style: .continuous))
                .overlay(
                    RoundedRectangle(cornerRadius: 22, style: .continuous)
                        .strokeBorder(Color.primary.opacity(0.07), lineWidth: 1)
                )
                .gesture(
                    SimultaneousGesture(
                        DragGesture()
                            .onChanged { v in
                                pan = CGSize(width: lastPan.width + v.translation.width,
                                             height: lastPan.height + v.translation.height)
                            }
                            .onEnded { _ in lastPan = pan },
                        MagnificationGesture()
                            .onChanged { val in
                                zoom = min(5.0, max(0.5, lastZoom * val))
                            }
                            .onEnded { _ in lastZoom = zoom }
                    )
                )
                .accessibilityLabel("Map of the recorded route with \(guide.places.count) saved places")

                // Top floating telemetry pill + recenter button
                VStack {
                    HStack(spacing: 12) {
                        Label("\(guide.steps) steps", systemImage: "shoeprints.fill")
                        Text("·").foregroundStyle(.tertiary)
                        Text(String(format: "%.1f m", distanceMeters))
                        Text("·").foregroundStyle(.tertiary)
                        Text(String(format: "%.0f°", guide.facing))
                    }
                    .font(.caption.weight(.semibold).monospacedDigit())
                    .padding(.horizontal, 12)
                    .padding(.vertical, 7)
                    .background(.ultraThinMaterial, in: Capsule())
                    .padding(.top, 12)

                    Spacer()

                    HStack {
                        if guide.trail.count < 2 {
                            Label("Start a route & walk to draw your trail", systemImage: "figure.walk")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                                .padding(.horizontal, 12)
                                .padding(.vertical, 7)
                                .background(.ultraThinMaterial, in: Capsule())
                        }
                        Spacer()
                        if zoom != 1.0 || pan != .zero {
                            Button {
                                withAnimation(.spring(response: 0.3, dampingFraction: 0.8)) {
                                    zoom = 1.0; lastZoom = 1.0; pan = .zero; lastPan = .zero
                                }
                            } label: {
                                Label("Recenter", systemImage: "scope")
                                    .font(.caption.weight(.semibold))
                                    .padding(.horizontal, 11)
                                    .padding(.vertical, 7)
                                    .background(.ultraThinMaterial, in: Capsule())
                            }
                            .buttonStyle(.plain)
                        }
                    }
                    .padding(12)
                }
            }

            // Legend bar
            HStack(spacing: 14) {
                legend(.green, "Start")
                legend(.orange, "Walked")
                legend(.purple, "Place")
                legend(.cyan, "Guidance")
                legend(.blue, "You")
            }
            .font(.caption.weight(.medium))
            .padding(.horizontal, 14)
            .padding(.vertical, 9)
            .frame(maxWidth: .infinity)
            .background(
                RoundedRectangle(cornerRadius: 14, style: .continuous)
                    .fill(Color(.secondarySystemGroupedBackground))
            )
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 12)
        .background(Color(.systemGroupedBackground))
    }

    private func legend(_ c: Color, _ t: String) -> some View {
        HStack(spacing: 5) {
            Circle().fill(c).frame(width: 8, height: 8)
            Text(t).foregroundStyle(.secondary)
        }
    }

    private func draw(_ ctx: GraphicsContext, _ size: CGSize) {
        var xs = guide.trail.map(\.x) + guide.places.map(\.x) + guide.waypoints.map { Double($0.x) } + [Double(guide.position.x), 0]
        var ys = guide.trail.map(\.y) + guide.places.map(\.y) + guide.waypoints.map { Double($0.y) } + [Double(guide.position.y), 0]
        xs += guide.backTrail.map(\.x); ys += guide.backTrail.map(\.y)
        let minX = xs.min() ?? 0, maxX = xs.max() ?? 0, minY = ys.min() ?? 0, maxY = ys.max() ?? 0
        let span = max(maxX - minX, maxY - minY, 8) + 4
        let baseScale = min(size.width, size.height) / span
        let scale = baseScale * Double(zoom)
        let cx = (minX + maxX) / 2, cy = (minY + maxY) / 2
        func pt(_ x: Double, _ y: Double) -> CGPoint {
            CGPoint(
                x: size.width / 2 + (x - cx) * scale + Double(pan.width),
                y: size.height / 2 - (y - cy) * scale + Double(pan.height)
            )
        }

        // 1 m grid (5 m when zoomed out)
        let step: Double = (span / Double(zoom)) > 36 ? 5 : 1
        var grid = Path()
        let halfW = Double(size.width) / max(scale, 1) + abs(Double(pan.width)) / max(scale, 1) + 10
        let halfH = Double(size.height) / max(scale, 1) + abs(Double(pan.height)) / max(scale, 1) + 10
        var gx = ((cx - halfW) / step).rounded(.down) * step
        while gx <= cx + halfW {
            grid.move(to: pt(gx, cy - halfH))
            grid.addLine(to: pt(gx, cy + halfH))
            gx += step
        }
        var gy = ((cy - halfH) / step).rounded(.down) * step
        while gy <= cy + halfH {
            grid.move(to: pt(cx - halfW, gy))
            grid.addLine(to: pt(cx + halfW, gy))
            gy += step
        }
        ctx.stroke(grid, with: .color(.primary.opacity(0.06)), lineWidth: 0.7)

        // Guidance corridor
        if guide.waypoints.count > 1 {
            var w = Path()
            w.move(to: pt(guide.waypoints[0].x, guide.waypoints[0].y))
            for p in guide.waypoints.dropFirst() { w.addLine(to: pt(p.x, p.y)) }
            ctx.stroke(w, with: .color(.cyan.opacity(0.25)), style: StrokeStyle(lineWidth: 12, lineCap: .round, lineJoin: .round))
            ctx.stroke(w, with: .color(.cyan), style: StrokeStyle(lineWidth: 4.5, lineCap: .round, lineJoin: .round, dash: [8, 7]))
        }

        // Walked trail; a re-anchor jump starts a new piece (never drawn as walked)
        func polyline(_ pts: [TrailPoint], _ color: Color, _ width: CGFloat) {
            guard pts.count > 1 else { return }
            var path = Path()
            for (i, p) in pts.enumerated() {
                if i == 0 || p.jump { path.move(to: pt(p.x, p.y)) } else { path.addLine(to: pt(p.x, p.y)) }
            }
            ctx.stroke(path, with: .color(color.opacity(0.22)), style: StrokeStyle(lineWidth: width + 5, lineCap: .round, lineJoin: .round))
            ctx.stroke(path, with: .color(color), style: StrokeStyle(lineWidth: width, lineCap: .round, lineJoin: .round))
        }
        polyline(guide.trail, .orange, 4)
        polyline(guide.backTrail, .blue, 3.5)

        // Origin / Start marker
        let s = pt(0, 0)
        ctx.fill(Path(ellipseIn: CGRect(x: s.x - 9, y: s.y - 9, width: 18, height: 18)), with: .color(.green.opacity(0.25)))
        ctx.fill(Path(ellipseIn: CGRect(x: s.x - 5.5, y: s.y - 5.5, width: 11, height: 11)), with: .color(.green))

        // Saved places
        for place in guide.places {
            let p = pt(place.x, place.y)
            ctx.fill(Path(ellipseIn: CGRect(x: p.x - 10, y: p.y - 10, width: 20, height: 20)), with: .color(.purple.opacity(0.22)))
            ctx.fill(Path(ellipseIn: CGRect(x: p.x - 6, y: p.y - 6, width: 12, height: 12)), with: .color(.purple))
            ctx.stroke(Path(ellipseIn: CGRect(x: p.x - 6, y: p.y - 6, width: 12, height: 12)), with: .color(.white), lineWidth: 1.5)
            ctx.draw(
                Text(place.label).font(.caption.weight(.bold)).foregroundColor(.primary),
                at: CGPoint(x: p.x + 11, y: p.y - 9),
                anchor: .leading
            )
        }

        // Walker position & live facing cone (heading is clockwise from +y)
        let me = pt(guide.position.x, guide.position.y)
        let a = guide.facing * .pi / 180
        func dir(_ da: Double, _ r: Double) -> CGPoint {
            CGPoint(x: me.x + sin(a + da) * r, y: me.y - cos(a + da) * r)
        }
        var cone = Path()
        cone.move(to: me)
        cone.addLine(to: dir(-0.42, 48))
        cone.addLine(to: dir(0.42, 48))
        cone.closeSubpath()
        ctx.fill(cone, with: .color(.blue.opacity(0.20)))

        var arrow = Path()
        arrow.move(to: dir(0, 17))
        arrow.addLine(to: dir(2.45, 10))
        arrow.addLine(to: dir(-2.45, 10))
        arrow.closeSubpath()
        ctx.fill(arrow, with: .color(.blue))

        ctx.fill(Path(ellipseIn: CGRect(x: me.x - 6.5, y: me.y - 6.5, width: 13, height: 13)), with: .color(.white))
        ctx.fill(Path(ellipseIn: CGRect(x: me.x - 5, y: me.y - 5, width: 10, height: 10)), with: .color(.blue))
    }
}
