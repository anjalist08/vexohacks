import SwiftUI

@main
struct WaybackHapticsApp: App {
    var body: some Scene {
        WindowGroup { ContentView() }
    }
}

struct ContentView: View {
    @StateObject private var link = Link()
    @AppStorage("address") private var address = ""

    var body: some View {
        NavigationStack {
            Form {
                Section("Laptop (main.py --host …)") {
                    Button("Find laptop automatically") { link.findLaptop { address = $0 } }
                        .buttonStyle(.borderedProminent)
                    TextField("or type the address main.py prints, e.g. 172.20.10.13:8790", text: $address)
                        .keyboardType(.numbersAndPunctuation)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                    HStack {
                        Button("Connect") { link.connect(address) }
                        Spacer()
                        Button("Disconnect", role: .destructive) { link.disconnect() }
                    }
                    Text(link.status).font(.footnote).foregroundStyle(.secondary)
                }
                Section("Last cue") {
                    Text(link.lastCue).font(.title2.bold())
                }
                Section("Try each pattern") {
                    LazyVGrid(columns: [GridItem(.adaptive(minimum: 140))], spacing: 8) {
                        ForEach(Cue.allCases) { cue in
                            Button(cue.title) { link.fire(cue) }
                                .buttonStyle(.bordered)
                                .frame(maxWidth: .infinity)
                        }
                    }
                }
                Section("Log") {
                    ForEach(link.log, id: \.self) { Text($0).font(.footnote.monospaced()) }
                }
            }
            .navigationTitle("Wayback haptics")
        }
        // Haptics only play while the app is open: keep the screen from locking.
        .onAppear { UIApplication.shared.isIdleTimerDisabled = true }
    }
}
