import SwiftUI

@main
struct WaybackApp: App {
    init() {
        // Keys can be handed over once at install time (launch environment) and are then kept in
        // the Keychain, so nobody types them on the phone. They are never in the code or in git.
        let env = ProcessInfo.processInfo.environment
        for (variable, name) in [("WAYBACK_DEEPGRAM_KEY", "deepgram"), ("WAYBACK_GEMINI_KEY", "gemini"),
                                 ("WAYBACK_ELEVENLABS_KEY", "elevenlabs")] {
            if let value = env[variable], !value.isEmpty { KeyStore.set(name, value) }
        }
        if let n = env["WAYBACK_BAND"].flatMap({ Int($0) }), (1...999).contains(n) {
            UserDefaults.standard.set(n, forKey: "bandNumber")
        }
    }

    var body: some Scene {
        WindowGroup {
            ContentView()
        }
    }
}
