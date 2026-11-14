import SwiftUI

/// The walked route as a map, like the trail page: the trail (orange), the way being guided
/// (dashed cyan), the walk back so far (blue), saved places (purple), the start (green), and
/// where you are with the way you face. +y is the direction you faced at "start route".
struct MapView: View {
    @ObservedObject var guide: Guide

    var body: some View {
        VStack(spacing: 10) {
            HStack {
                Text("Map").font(.title2.bold())
                Spacer()
                if !guide.mode.isEmpty && guide.mode != "LIVE" {
                    Text(guide.mode).font(.caption.bold()).foregroundStyle(.orange)
                }
                Text("\(guide.steps) steps").font(.callout.monospacedDigit()).foregroundStyle(.secondary)
            }
            Canvas { ctx, size in draw(ctx, size) }
                .background(RoundedRectangle(cornerRadius: 16).fill(Color(.secondarySystemBackground)))
                .clipShape(RoundedRectangle(cornerRadius: 16))
                .accessibilityLabel("Map of the recorded route with \(guide.places.count) saved places")
            HStack(spacing: 14) {
                legend(.green, "Start"); legend(.orange, "Walked"); legend(.purple, "Place")
                legend(.cyan, "Way back"); legend(.blue, "You")
            }
            .font(.caption)
            if guide.trail.count < 2 {
                Text("Start a route and walk: the trail appears here.").font(.footnote).foregroundStyle(.secondary)
            }
        }
        .padding()
    }

    private func legend(_ c: Color, _ t: String) -> some View {
        HStack(spacing: 4) { Circle().fill(c).frame(width: 8, height: 8); Text(t) }
    }

    private func draw(_ ctx: GraphicsContext, _ size: CGSize) {
        // Fit everything with a margin; at least 8 m across so a short walk is not huge.
        var xs = guide.trail.map(\.x) + guide.places.map(\.x) + guide.waypoints.map { Double($0.x) } + [Double(guide.position.x), 0]
        var ys = guide.trail.map(\.y) + guide.places.map(\.y) + guide.waypoints.map { Double($0.y) } + [Double(guide.position.y), 0]
        xs += guide.backTrail.map(\.x); ys += guide.backTrail.map(\.y)
        let minX = xs.min() ?? 0, maxX = xs.max() ?? 0, minY = ys.min() ?? 0, maxY = ys.max() ?? 0
        let span = max(maxX - minX, maxY - minY, 8) + 4
        let scale = min(size.width, size.height) / span
        let cx = (minX + maxX) / 2, cy = (minY + maxY) / 2
        func pt(_ x: Double, _ y: Double) -> CGPoint {
            CGPoint(x: size.width / 2 + (x - cx) * scale, y: size.height / 2 - (y - cy) * scale)
        }

        // 1 m grid (5 m when zoomed out)
        let step: Double = span > 40 ? 5 : 1
        var grid = Path()
        var gx = (cx - Double(size.width) / scale / 2).rounded(.down)
        while gx < cx + Double(size.width) / scale / 2 {
            if gx.truncatingRemainder(dividingBy: step) == 0 { grid.move(to: pt(gx, cy - 1000)); grid.addLine(to: pt(gx, cy + 1000)) }
            gx += 1
        }
        var gy = (cy - Double(size.height) / scale / 2).rounded(.down)
        while gy < cy + Double(size.height) / scale / 2 {
            if gy.truncatingRemainder(dividingBy: step) == 0 { grid.move(to: pt(cx - 1000, gy)); grid.addLine(to: pt(cx + 1000, gy)) }
            gy += 1
        }
        ctx.stroke(grid, with: .color(.gray.opacity(0.15)), lineWidth: 0.5)

        // the way being guided
        if guide.waypoints.count > 1 {
            var w = Path()
            w.move(to: pt(guide.waypoints[0].x, guide.waypoints[0].y))
            for p in guide.waypoints.dropFirst() { w.addLine(to: pt(p.x, p.y)) }
            ctx.stroke(w, with: .color(.cyan), style: StrokeStyle(lineWidth: 6, lineCap: .round, lineJoin: .round, dash: [8, 8]))
        }
        // walked trail; a re-anchor jump starts a new piece (never drawn as walked)
        func polyline(_ pts: [TrailPoint], _ color: Color, _ width: CGFloat) {
            guard pts.count > 1 else { return }
            var path = Path()
            for (i, p) in pts.enumerated() {
                if i == 0 || p.jump { path.move(to: pt(p.x, p.y)) } else { path.addLine(to: pt(p.x, p.y)) }
            }
            ctx.stroke(path, with: .color(color), style: StrokeStyle(lineWidth: width, lineCap: .round, lineJoin: .round))
        }
        polyline(guide.trail, .orange, 4)
        polyline(guide.backTrail, .blue, 3)

        // start
        let s = pt(0, 0)
        ctx.fill(Path(ellipseIn: CGRect(x: s.x - 6, y: s.y - 6, width: 12, height: 12)), with: .color(.green))

        // places
        for place in guide.places {
            let p = pt(place.x, place.y)
            ctx.fill(Path(ellipseIn: CGRect(x: p.x - 7, y: p.y - 7, width: 14, height: 14)), with: .color(.purple))
            ctx.draw(Text(place.label).font(.caption.bold()), at: CGPoint(x: p.x + 10, y: p.y - 10), anchor: .leading)
        }

        // you, and the way you face (heading is clockwise from +y)
        let me = pt(guide.position.x, guide.position.y)
        let a = guide.facing * .pi / 180
        func dir(_ da: Double, _ r: Double) -> CGPoint {
            CGPoint(x: me.x + sin(a + da) * r, y: me.y - cos(a + da) * r)
        }
        var cone = Path()
        cone.move(to: me); cone.addLine(to: dir(-0.45, 46)); cone.addLine(to: dir(0.45, 46)); cone.closeSubpath()
        ctx.fill(cone, with: .color(.blue.opacity(0.18)))
        var arrow = Path()
        arrow.move(to: dir(0, 16)); arrow.addLine(to: dir(2.5, 10)); arrow.addLine(to: dir(-2.5, 10)); arrow.closeSubpath()
        ctx.fill(arrow, with: .color(.blue))
        ctx.fill(Path(ellipseIn: CGRect(x: me.x - 5, y: me.y - 5, width: 10, height: 10)), with: .color(.blue))
    }
}
