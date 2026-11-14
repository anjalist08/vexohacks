import SwiftUI

/// Record a route, save places with one tap or voice, and trigger turn-by-turn return guidance.
struct PlacesView: View {
    @ObservedObject var guide: Guide
    @State private var newPlace = ""
    @State private var typed = ""

    private let quickSpots = ["entrance", "kitchen", "elevator", "stairs", "desk"]

    private func turnIcon(_ turn: String) -> String {
        switch turn {
        case "left": return "arrow.turn.up.left"
        case "right": return "arrow.turn.up.right"
        case "around": return "arrow.uturn.down"
        case "arrive": return "flag.checkered.2.crossed"
        default: return "arrow.up"
        }
    }

    var body: some View {
        NavigationStack {
            List {
                // Route Recording Section
                Section {
                    HStack(spacing: 12) {
                        Image(systemName: guide.recording ? "record.circle.fill" : "pause.circle.fill")
                            .font(.title2)
                            .foregroundStyle(guide.recording ? (guide.calibrated ? .green : .orange) : .secondary)

                        VStack(alignment: .leading, spacing: 2) {
                            Text(guide.recording ? (guide.calibrated ? "Recording Trail" : "Calibrating — Hold Arm Still")
                                                 : "Route Idle")
                                .font(.subheadline.weight(.semibold))
                            Text("\(guide.steps) steps · \(String(format: "%.1f m", Double(guide.steps) * guide.stepLength))")
                                .font(.caption.monospacedDigit())
                                .foregroundStyle(.secondary)
                        }
                        Spacer()
                    }
                    .padding(.vertical, 2)

                    HStack(spacing: 10) {
                        Button {
                            guide.command("start route")
                        } label: {
                            Label("Start Route", systemImage: "play.fill")
                                .frame(maxWidth: .infinity)
                        }
                        .buttonStyle(.borderedProminent)
                        .tint(.green)

                        Button {
                            guide.command("stop route")
                        } label: {
                            Label("Stop", systemImage: "stop.fill")
                                .frame(maxWidth: .infinity)
                        }
                        .buttonStyle(.bordered)
                    }
                } header: {
                    Text("Trail Recording")
                } footer: {
                    Text("Tap Start Route, keep your wrist still for ~1 s so the gyro calibrates, then walk normally.")
                }

                // Quick Save Section
                Section {
                    HStack(spacing: 10) {
                        Image(systemName: "mappin.and.ellipse")
                            .foregroundStyle(.purple)
                        TextField("Name this spot (e.g. coffee bar)…", text: $newPlace)
                            .textInputAutocapitalization(.never)
                            .submitLabel(.done)
                            .onSubmit(save)
                        Button("Save", action: save)
                            .buttonStyle(.borderedProminent)
                            .tint(.purple)
                            .disabled(newPlace.trimmingCharacters(in: .whitespaces).isEmpty)
                    }

                    ScrollView(.horizontal, showsIndicators: false) {
                        HStack(spacing: 8) {
                            ForEach(quickSpots, id: \.self) { preset in
                                Button {
                                    guide.command("remember this as the \(preset)")
                                } label: {
                                    Label(preset.capitalized, systemImage: "plus")
                                        .font(.caption.weight(.medium))
                                }
                                .buttonStyle(.bordered)
                                .controlSize(.small)
                            }
                        }
                        .padding(.vertical, 2)
                    }
                } header: {
                    Text("Pin Current Location")
                } footer: {
                    Text("Tap a preset chip to pin immediately, or double-tap the band and say \"this is the kitchen\".")
                }

                // Saved Places List
                Section {
                    if guide.places.isEmpty {
                        HStack(spacing: 10) {
                            Image(systemName: "sparkles")
                                .foregroundStyle(.secondary)
                            Text("No places pinned yet — start a route and save spots along the way.")
                                .font(.footnote)
                                .foregroundStyle(.secondary)
                        }
                        .padding(.vertical, 4)
                    }

                    ForEach(guide.places) { place in
                        VStack(alignment: .leading, spacing: 8) {
                            HStack {
                                Image(systemName: "mappin.circle.fill")
                                    .font(.title3)
                                    .foregroundStyle(.purple)
                                Text(place.label.capitalized)
                                    .font(.headline)
                                if let floor = place.floor {
                                    Text("Floor \(floor)")
                                        .font(.caption2.weight(.semibold))
                                        .padding(.horizontal, 7)
                                        .padding(.vertical, 2)
                                        .background(Capsule().fill(Color.secondary.opacity(0.15)))
                                }
                                Spacer()
                                if guide.guiding && guide.guideTarget == place.label {
                                    Text("GUIDING")
                                        .font(.caption2.weight(.bold))
                                        .padding(.horizontal, 8)
                                        .padding(.vertical, 3)
                                        .background(Capsule().fill(Color.green.opacity(0.18)))
                                        .foregroundStyle(.green)
                                }
                            }

                            if let note = place.note, !note.isEmpty {
                                Text(note)
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                            }

                            HStack(spacing: 10) {
                                Button {
                                    guide.command("take me to the \(place.label)")
                                } label: {
                                    Label("Guide Me Here", systemImage: "figure.walk")
                                        .frame(maxWidth: .infinity)
                                }
                                .buttonStyle(.borderedProminent)
                                .controlSize(.small)

                                Button {
                                    guide.command("I'm at the \(place.label)")
                                } label: {
                                    Label("I'm Here", systemImage: "scope")
                                        .frame(maxWidth: .infinity)
                                }
                                .buttonStyle(.bordered)
                                .controlSize(.small)
                            }
                        }
                        .padding(.vertical, 4)
                    }

                    Button {
                        guide.command("take me back to the start")
                    } label: {
                        Label("Guide Me Back to Start", systemImage: "arrow.uturn.backward.circle.fill")
                            .fontWeight(.medium)
                    }
                } header: {
                    Text("Saved Places (\(guide.places.count))")
                }

                // Active Turn-by-Turn Leg List
                if !guide.directions.isEmpty {
                    Section {
                        ForEach(guide.directions) { d in
                            let current = guide.guiding && d.id == guide.directionIndex
                            let done = guide.guiding && d.id < guide.directionIndex
                            HStack(spacing: 12) {
                                Image(systemName: done ? "checkmark.circle.fill" : turnIcon(d.turn))
                                    .foregroundStyle(done ? .green : current ? .accentColor : .secondary)
                                    .frame(width: 24)
                                Text(d.text)
                                    .font(.subheadline)
                                    .fontWeight(current ? .bold : .regular)
                                    .foregroundStyle(done ? .secondary : .primary)
                            }
                            .padding(.vertical, 2)
                        }
                    } header: {
                        Text(guide.guiding ? "Active Route → \(guide.guideTarget.capitalized)" : "Last Computed Directions")
                    }
                }

                // Natural Language Command Box
                Section {
                    HStack(spacing: 10) {
                        Image(systemName: "sparkles.rectangle.stack")
                            .foregroundStyle(.tint)
                        TextField("Ask anything (e.g. \"where is the elevator?\")", text: $typed)
                            .textInputAutocapitalization(.never)
                            .submitLabel(.send)
                            .onSubmit { guide.command(typed); typed = "" }
                        Button("Send") {
                            guide.command(typed)
                            typed = ""
                        }
                        .buttonStyle(.borderedProminent)
                        .controlSize(.small)
                        .disabled(typed.trimmingCharacters(in: .whitespaces).isEmpty)
                    }
                    if !guide.voice.isEmpty {
                        Text(guide.voice)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                } header: {
                    Text("Voice / Text Command")
                }
            }
            .navigationTitle("Places")
            .navigationBarTitleDisplayMode(.inline)
        }
    }

    private func save() {
        let name = newPlace.trimmingCharacters(in: .whitespaces)
        guard !name.isEmpty else { return }
        guide.command("remember this as the \(name)")
        newPlace = ""
    }
}
