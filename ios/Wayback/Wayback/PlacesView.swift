import SwiftUI

/// Record a route, save places ("this is the kitchen"), and ask to be guided to one.
/// Every button sends the same words you could say after a double-tap, so it all goes
/// through the laptop app's Gemini and keyword fallback, like the trail page.
struct PlacesView: View {
    @ObservedObject var guide: Guide
    @State private var newPlace = ""
    @State private var typed = ""

    private func turnIcon(_ turn: String) -> String {
        switch turn {
        case "left": return "arrow.turn.up.left"
        case "right": return "arrow.turn.up.right"
        case "around": return "arrow.uturn.down"
        case "arrive": return "mappin.circle.fill"
        default: return "arrow.up"
        }
    }

    var body: some View {
        List {
            Section {
                HStack {
                    Label(guide.recording ? (guide.calibrated ? "Recording" : "Calibrating — hold still")
                                          : "Not recording",
                          systemImage: guide.recording ? "record.circle" : "pause.circle")
                        .foregroundStyle(guide.recording ? (guide.calibrated ? .green : .orange) : .secondary)
                    Spacer()
                    Text("\(guide.steps) steps").monospacedDigit().foregroundStyle(.secondary)
                }
                HStack {
                    Button { guide.command("start route") } label: { Label("Start route", systemImage: "play.fill") }
                        .buttonStyle(.borderedProminent)
                    Button { guide.command("stop route") } label: { Label("Stop", systemImage: "stop.fill") }
                        .buttonStyle(.bordered)
                }
                Text("Start a route, hold your arm still a moment, then walk.")
                    .font(.footnote).foregroundStyle(.secondary)
            } header: { Text("Route") }

            Section {
                HStack {
                    TextField("kitchen, stairs, entrance…", text: $newPlace)
                        .textInputAutocapitalization(.never)
                        .submitLabel(.done)
                        .onSubmit(save)
                    Button("Save", action: save).buttonStyle(.borderedProminent).disabled(newPlace.isEmpty)
                }
                Text("Saves where you are standing now. Or double-tap the band and say \"this is the kitchen\".")
                    .font(.footnote).foregroundStyle(.secondary)
            } header: { Text("Save this spot as") }

            Section {
                if guide.places.isEmpty {
                    Text("No places yet.").foregroundStyle(.secondary)
                }
                ForEach(guide.places) { place in
                    VStack(alignment: .leading, spacing: 6) {
                        HStack {
                            Image(systemName: "mappin.circle.fill").foregroundStyle(.purple)
                            Text(place.label).font(.headline)
                            if let floor = place.floor { Text("floor \(floor)").font(.caption).foregroundStyle(.secondary) }
                            Spacer()
                            if guide.guiding && guide.guideTarget == place.label {
                                Text("guiding").font(.caption.bold()).foregroundStyle(.green)
                            }
                        }
                        if let note = place.note, !note.isEmpty {
                            Text(note).font(.footnote).foregroundStyle(.secondary)
                        }
                        HStack {
                            Button { guide.command("take me to the \(place.label)") } label: {
                                Label("Take me here", systemImage: "figure.walk")
                            }.buttonStyle(.borderedProminent)
                            Button { guide.command("I'm at the \(place.label)") } label: {
                                Label("I'm here", systemImage: "scope")
                            }.buttonStyle(.bordered)
                        }
                        .font(.footnote)
                    }
                    .padding(.vertical, 4)
                }
                Button { guide.command("take me back to the start") } label: {
                    Label("Take me back to the start", systemImage: "arrow.uturn.backward")
                }
            } header: { Text("Places (\(guide.places.count))") }

            if !guide.directions.isEmpty {
                Section {
                    ForEach(guide.directions) { d in
                        HStack {
                            Image(systemName: turnIcon(d.turn)).frame(width: 26)
                            Text(d.text)
                                .fontWeight(guide.guiding && d.id == guide.directionIndex ? .bold : .regular)
                                .foregroundStyle(guide.guiding && d.id < guide.directionIndex ? .secondary : .primary)
                        }
                    }
                } header: {
                    Text(guide.guiding ? "Directions to the \(guide.guideTarget)" : "Last directions")
                }
            }

            Section {
                HStack {
                    TextField("Type anything you'd say", text: $typed)
                        .textInputAutocapitalization(.never)
                        .submitLabel(.send)
                        .onSubmit { guide.command(typed); typed = "" }
                    Button("Send") { guide.command(typed); typed = "" }.disabled(typed.isEmpty)
                }
                if !guide.voice.isEmpty { Text(guide.voice).font(.footnote).foregroundStyle(.secondary) }
            } header: { Text("Command") }
        }
    }

    private func save() {
        let name = newPlace.trimmingCharacters(in: .whitespaces)
        guard !name.isEmpty else { return }
        guide.command("remember this as the \(name)")
        newPlace = ""
    }
}
