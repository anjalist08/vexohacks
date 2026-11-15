import SwiftUI

/// Centralized design tokens and reusable visual styles for Wayback.
/// Edit values here in Xcode to customize the app's look and feel across all screens.
enum WaybackTheme {
    // MARK: - Brand Palette

    static let brand = Color.accentColor
    static let routeColor = Color(red: 0.08, green: 0.48, blue: 0.98)
    static let guideColor = Color(red: 0.12, green: 0.76, blue: 0.46)
    static let landmarkColor = Color(red: 0.62, green: 0.28, blue: 0.94)

    static func stateColor(for state: String) -> Color {
        switch state {
        case "on": return guideColor
        case "wrong": return .orange
        case "lost": return .red
        case "done": return landmarkColor
        default: return routeColor
        }
    }

    // MARK: - Quick Landmark Presets

    static let quickPlacePresets: [(label: String, icon: String)] = [
        ("entrance", "door.left.hand.open"),
        ("elevator", "arrow.up.arrow.down.square"),
        ("stairs", "stairs"),
        ("kitchen", "cup.and.saucer.fill"),
        ("restroom", "figure.dress.line.vertical.figure"),
        ("desk", "desktopcomputer"),
        ("exit", "rectangle.portrait.and.arrow.right"),
    ]

    // MARK: - Corner Radii

    static let dockCornerRadius: CGFloat = 30
    static let cardCornerRadius: CGFloat = 22
    static let compactCornerRadius: CGFloat = 18
}

/// Reusable brand squircle displaying the Wayback app logo.
struct WaybackLogoMark: View {
    var size: CGFloat = 34

    var body: some View {
        Image("WaybackLogo")
            .resizable()
            .interpolation(.high)
            .scaledToFill()
            .frame(width: size, height: size)
            .clipShape(RoundedRectangle(cornerRadius: size * 0.24, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: size * 0.24, style: .continuous)
                    .strokeBorder(Color.cyan.opacity(0.30), lineWidth: max(0.8, size * 0.025))
            )
            .accessibilityHidden(true)
    }
}

/// Clean elevated floating surface style that adapts cleanly to both Light and Dark Mode.
struct FloatingSurfaceModifier: ViewModifier {
    var cornerRadius: CGFloat = WaybackTheme.cardCornerRadius

    func body(content: Content) -> some View {
        content
            .background(
                RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
                    .fill(.ultraThinMaterial)
                    .background(
                        RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
                            .fill(Color(.systemBackground).opacity(0.82))
                    )
            )
            .overlay(
                RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
                    .strokeBorder(Color.primary.opacity(0.07), lineWidth: 0.8)
            )
            .shadow(color: .black.opacity(0.09), radius: 14, y: 5)
    }
}

extension View {
    func floatingCard(cornerRadius: CGFloat = WaybackTheme.cardCornerRadius) -> some View {
        modifier(FloatingSurfaceModifier(cornerRadius: cornerRadius))
    }

    func floatingCapsule() -> some View {
        self
            .background(
                Capsule()
                    .fill(.ultraThinMaterial)
                    .background(Capsule().fill(Color(.systemBackground).opacity(0.84)))
            )
            .overlay(Capsule().strokeBorder(Color.primary.opacity(0.07), lineWidth: 0.8))
            .shadow(color: .black.opacity(0.08), radius: 10, y: 3)
    }
}
