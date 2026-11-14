import CoreBluetooth
import Foundation

/// The iPhone's Bluetooth link to the team's band (BandConfig.number, and only that band).
/// It relays everything the band sends to the laptop app as `band_event` messages, and runs
/// the laptop's `band_cmd` messages (configure, setLed, ledOff) on the band, exactly like the
/// Chrome bridge (web/band-relay.js), so `python3 main.py --bridge --phone` needs no change.
final class BandLink: NSObject, CBCentralManagerDelegate, CBPeripheralDelegate {
    var onStatus: ((String) -> Void)?             // "searching", "connected", "disconnected", or a problem
    var onMessage: (([String: Any]) -> Void)?     // band_event / band_status messages for the laptop

    private var central: CBCentralManager!
    private var peripheral: CBPeripheral?
    private var rxChar: CBCharacteristic?
    private var wantConnected = false
    private var verified = false
    private var seq: UInt8 = 0
    private var queue: [[UInt8]] = []             // commands wait their turn: one at a time
    private var waiting: (seq: UInt8, sentAt: Date)?
    private var clockAnchor: (tMs: UInt32, at: Double)?

    override init() {
        super.init()
        central = CBCentralManager(delegate: self, queue: .main)
    }

    /// This iPhone's identifier for the team's band, saved after its number was checked, so the
    /// app can reconnect to it directly (no scan, no double-tap while it can be found).
    private static let savedKey = "waybackBandIdentifier"

    /// iOS 17 can keep the link by itself (auto-reconnect). iOS refuses that option ("One or more
    /// parameters were invalid") unless the delegate also has the isReconnecting disconnect callback,
    /// which is below. If iOS still refuses it, we drop the option and connect the plain way.
    private var useAutoReconnect = true
    private var connectOptions: [String: Any] {
        if useAutoReconnect, #available(iOS 17.0, *) { return [CBConnectPeripheralOptionEnableAutoReconnect: true] }
        return [:]
    }

    /// A connect found by scanning must reach "verified" (GET_INFO answered) in this many seconds,
    /// or we let go and scan again, like the kit's connectSeconds.
    private static let connectSeconds = 12.0
    private var attempt = 0

    func start() {
        wantConnected = true
        connectRemembered()
        scanIfReady()
    }

    /// Ask iOS to connect to the remembered band. The request never times out: it completes as
    /// soon as the band can be found (after a double-tap, a restart, or for 2 min after a drop).
    /// We scan at the same time, so a band found by scanning takes over if this one stays silent.
    private func connectRemembered() {
        guard wantConnected, central.state == .poweredOn, peripheral == nil,
              let s = UserDefaults.standard.string(forKey: BandLink.savedKey), let id = UUID(uuidString: s),
              let p = central.retrievePeripherals(withIdentifiers: [id]).first else { return }
        peripheral = p
        p.delegate = self
        onStatus?("Waiting for \(BandConfig.name)… double-tap the band")
        central.connect(p, options: connectOptions)
    }

    func stop() {
        wantConnected = false
        attempt += 1
        central.stopScan()
        if let p = peripheral { central.cancelPeripheralConnection(p) }
    }

    /// Scan unless a link is up or being set up. A pending remembered connect does not stop the scan.
    private func scanIfReady() {
        guard wantConnected, central.state == .poweredOn, !verified,
              peripheral == nil || peripheral?.state == .disconnected || peripheral?.state == .connecting
                && UserDefaults.standard.string(forKey: BandLink.savedKey) == peripheral?.identifier.uuidString
        else { return }
        if peripheral == nil { onStatus?("Looking for \(BandConfig.name)… double-tap the band") }
        central.scanForPeripherals(withServices: [CBUUID(string: BandProtocol.service)], options: nil)
    }

    // MARK: finding only our band

    func centralManagerDidUpdateState(_ c: CBCentralManager) {
        switch c.state {
        case .poweredOn: connectRemembered(); scanIfReady()
        case .unauthorized: onStatus?("Bluetooth not allowed: Settings → Wayback → Bluetooth")
        case .poweredOff: onStatus?("Turn Bluetooth on")
        default: break
        }
    }

    func centralManager(_ c: CBCentralManager, didDiscover p: CBPeripheral, advertisementData ad: [String: Any], rssi: NSNumber) {
        let name = ad[CBAdvertisementDataLocalNameKey] as? String
        let maker = (ad[CBAdvertisementDataManufacturerDataKey] as? Data).map { [UInt8]($0) }
        let numberInAdvert = maker.flatMap { BandProtocol.bandNumber(fromManufacturerData: $0) }
        // Exact name, or the number in the advertising packet. Never any other band.
        guard name == BandConfig.name || numberInAdvert == BandConfig.number else { return }
        c.stopScan()
        if let old = peripheral, old !== p { c.cancelPeripheralConnection(old) }   // a stale remembered request
        peripheral = p
        p.delegate = self
        onStatus?("Found \(BandConfig.name), connecting…")
        c.connect(p, options: connectOptions)
        watchdog(p)
    }

    /// If the link is not verified in time, let the band go and look again (it is still findable).
    private func watchdog(_ p: CBPeripheral) {
        attempt += 1
        let mine = attempt
        DispatchQueue.main.asyncAfter(deadline: .now() + BandLink.connectSeconds) { [weak self] in
            guard let self, self.attempt == mine, self.wantConnected, !self.verified, self.peripheral === p else { return }
            self.onStatus?("\(BandConfig.name) did not answer. Trying again… (double-tap the band if its light is off)")
            self.central.cancelPeripheralConnection(p)
            self.reset()
            self.scanIfReady()
        }
    }

    func centralManager(_ c: CBCentralManager, didConnect p: CBPeripheral) {
        c.stopScan()
        peripheral = p
        p.delegate = self
        onStatus?("Connected, checking it is band \(BandConfig.number)…")
        p.discoverServices([CBUUID(string: BandProtocol.service)])
        if attempt == 0 || !verified { watchdog(p) }
    }

    func centralManager(_ c: CBCentralManager, didFailToConnect p: CBPeripheral, error: Error?) {
        let why = error?.localizedDescription ?? "no reason given"
        if useAutoReconnect, (error as? CBError)?.code == .invalidParameters || why.lowercased().contains("invalid") {
            useAutoReconnect = false                       // this iOS refuses auto-reconnect: connect plainly
            onStatus?("Connecting to \(BandConfig.name)…")
            c.connect(p, options: connectOptions)
            return
        }
        reset()
        onStatus?("Could not connect (\(why)). Double-tap the band and try again.")
        scanIfReady()
    }

    /// iOS 17 and later call this one (it must exist for auto-reconnect to be allowed).
    func centralManager(_ c: CBCentralManager, didDisconnectPeripheral p: CBPeripheral, timestamp: CFAbsoluteTime,
                        isReconnecting: Bool, error: Error?) {
        if isReconnecting && wantConnected {
            let was = verified
            reset()
            peripheral = p                                 // iOS is reconnecting to it by itself
            if was { onMessage?(["type": "band_status", "status": "reconnecting"]) }
            onStatus?("Link lost, reconnecting to \(BandConfig.name)…")
            return
        }
        lostLink(c, p)
    }

    func centralManager(_ c: CBCentralManager, didDisconnectPeripheral p: CBPeripheral, error: Error?) {
        lostLink(c, p)
    }

    private func lostLink(_ c: CBCentralManager, _ p: CBPeripheral) {
        let was = verified
        reset()
        if was { onMessage?(["type": "band_status", "status": "reconnecting"]) }
        guard wantConnected else { return }               // stopped on purpose, or refused: keep that message
        // Keep the link: the band can be found again for 2 minutes after a drop. Reconnect to the
        // same band directly; it is checked again (GET_INFO) and set up again when it answers.
        if was {
            peripheral = p
            p.delegate = self
            onStatus?("Link lost, reconnecting to \(BandConfig.name)…")
            c.connect(p, options: connectOptions)
        }
        scanIfReady()
    }

    private func reset() {
        peripheral = nil; rxChar = nil; verified = false; queue = []; waiting = nil; clockAnchor = nil
    }

    // MARK: services

    private func failed(_ step: String, _ error: Error?, _ p: CBPeripheral) {
        onStatus?("\(step) failed: \(error?.localizedDescription ?? "not found"). Trying again…")
        central.cancelPeripheralConnection(p)              // the disconnect callback scans again
    }

    func peripheral(_ p: CBPeripheral, didDiscoverServices error: Error?) {
        guard error == nil, let s = p.services?.first(where: { $0.uuid == CBUUID(string: BandProtocol.service) }) else {
            return failed("Finding the band's service", error, p)
        }
        p.discoverCharacteristics([CBUUID(string: BandProtocol.rx), CBUUID(string: BandProtocol.tx)], for: s)
    }

    func peripheral(_ p: CBPeripheral, didDiscoverCharacteristicsFor s: CBService, error: Error?) {
        let chars = s.characteristics ?? []
        guard error == nil, let rx = chars.first(where: { $0.uuid == CBUUID(string: BandProtocol.rx) }),
              let tx = chars.first(where: { $0.uuid == CBUUID(string: BandProtocol.tx) }) else {
            return failed("Reading the band's channels", error, p)
        }
        rxChar = rx
        p.setNotifyValue(true, for: tx)                    // listen before the first command
    }

    func peripheral(_ p: CBPeripheral, didUpdateNotificationStateFor ch: CBCharacteristic, error: Error?) {
        guard ch.uuid == CBUUID(string: BandProtocol.tx) else { return }
        guard error == nil, ch.isNotifying else { return failed("Listening to the band", error, p) }
        send(BandProtocol.Op.getInfo)            // first: is this really our band?
    }

    func peripheral(_ p: CBPeripheral, didWriteValueFor ch: CBCharacteristic, error: Error?) {
        if let error, !verified { onStatus?("Sending to the band failed: \(error.localizedDescription)") }
    }

    // MARK: commands, one at a time (contract: wait for each response, 2 s timeout)

    private func send(_ op: BandProtocol.Op, _ args: [UInt8] = []) {
        seq = seq &+ 1
        queue.append(BandProtocol.command(seq: seq, op, args))
        pump()
    }

    private func pump() {
        if let w = waiting, Date().timeIntervalSince(w.sentAt) < 2 { return }
        waiting = nil
        guard !queue.isEmpty, let p = peripheral, let rx = rxChar else { return }
        let frame = queue.removeFirst()
        waiting = (frame[1], Date())
        p.writeValue(Data(frame), for: rx, type: .withResponse)
        DispatchQueue.main.asyncAfter(deadline: .now() + 2.1) { [weak self] in self?.pump() }
    }

    func peripheral(_ p: CBPeripheral, didUpdateValueFor ch: CBCharacteristic, error: Error?) {
        guard let value = ch.value, let frame = BandProtocol.parse([UInt8](value)) else { return }
        switch frame {
        case .response(let s, let op, let status, let data):
            guard s == waiting?.seq else { return }
            waiting = nil
            if op == BandProtocol.Op.getInfo.rawValue && !verified {
                guard status == 0, BandProtocol.bandNumber(fromInfo: data) == BandConfig.number else {
                    onStatus?("That is not band \(BandConfig.number). Disconnected.")   // rule: never use another band
                    wantConnected = false
                    central.cancelPeripheralConnection(p)
                    return
                }
                verified = true
                UserDefaults.standard.set(p.identifier.uuidString, forKey: BandLink.savedKey)   // checked: remember it
                onStatus?("\(BandConfig.name) connected (iPhone Bluetooth)")
                onMessage?(["type": "band_status", "status": "connected", "name": BandConfig.name,
                            "transport": "iPhone Bluetooth"])
            }
            pump()
        default:
            if verified { relay(frame) }
        }
    }

    // MARK: band -> laptop

    /// Real time (seconds since 1970) for the band's millisecond counter, anchored on first sight.
    private func time(_ tMs: UInt32) -> Double {
        let now = Date().timeIntervalSince1970
        if clockAnchor == nil || tMs < clockAnchor!.tMs { clockAnchor = (tMs, now) }
        return clockAnchor!.at + Double(tMs - clockAnchor!.tMs) / 1000
    }

    private func relay(_ frame: BandProtocol.Frame) {
        func event(_ kind: String, _ fields: [String: Any]) {
            onMessage?(fields.merging(["type": "band_event", "kind": kind]) { a, _ in a })
        }
        switch frame {
        case .motion(let t, let period, let samples):
            for (i, s) in samples.enumerated() {
                event("motion", ["time": time(t + UInt32(i) * UInt32(period)),
                                 "ax": s[0], "ay": s[1], "az": s[2], "gx": s[3], "gy": s[4], "gz": s[5]])
            }
        case .event(let t, let kind, let arg):
            event("event", ["time": time(t), "event": kind, "arg": Int(arg)])
        case .activity(let t, let steps, let cadence, let state, let motion):
            event("activity", ["time": time(t), "steps": Int(steps), "cadence": Int(cadence), "state": state, "motion": motion])
        case .audio(let s, let opus):
            event("audio", ["seq": Int(s), "opus": Data(opus).base64EncodedString()])
        case .battery(let pct, let state, let mv):
            event("battery", ["percent": Int(pct), "state": state, "millivolts": Int(mv)])
        case .temp(let t, let c):
            event("temperature", ["time": time(t), "celsius": c])
        default:
            break
        }
    }

    // MARK: laptop -> band (band_cmd)

    func run(command m: [String: Any]) {
        guard verified, let op = m["op"] as? String else { return }
        let a = m["args"] as? [String: Any] ?? [:]
        switch op {
        case "configure": configure(a)
        case "setLed":
            send(.ledSet, BandProtocol.ledArgs(color: a["color"] as? String ?? "#ffffff",
                                               brightness: (a["brightness"] as? Double) ?? 1,
                                               pattern: a["pattern"] as? String ?? "solid",
                                               periodMs: (a["period"] as? Int) ?? 1000))
        case "ledOff":
            send(.ledSet, BandProtocol.ledArgs(color: "#000000", brightness: 0, pattern: "off", periodMs: 1000))
        default: break
        }
    }

    /// The kit's configure(...) names, turned into the band's commands.
    private func configure(_ a: [String: Any]) {
        var start: [BandProtocol.Stream] = [], stopping: [BandProtocol.Stream] = []
        func on(_ v: Any?) -> Bool? {
            switch v {
            case let b as Bool: return b
            case let n as NSNumber: return n.doubleValue > 0
            case is String: return true                 // "fastest"
            default: return nil
            }
        }
        if let rate = a["motion"] as? Int, rate > 0 {
            send(.imuSet, [UInt8([10, 25, 50, 100].contains(rate) ? rate : 50), 2] + BandProtocol.u16(2000))
        }
        if let v = on(a["motion"]) { v ? start.append(.motion) : stopping.append(.motion) }
        if let v = on(a["events"]) { v ? start.append(.event) : stopping.append(.event) }
        if let v = on(a["activity"]) {
            if v { send(.streamSetInterval, [UInt8(BandProtocol.Stream.activity.rawValue)] + BandProtocol.u32(100)) }
            v ? start.append(.activity) : stopping.append(.activity)
        }
        if let v = on(a["battery"]) { v ? start.append(.battery) : stopping.append(.battery) }
        if let v = on(a["temperature"]) {
            if v, let s = a["temperature"] as? Int, (1...255).contains(s) { send(.tempSetInterval, [UInt8(s)]) }
            v ? start.append(.temp) : stopping.append(.temp)
        }
        if let v = on(a["audio"]) { v ? start.append(.audio) : stopping.append(.audio) }
        if !stopping.isEmpty { send(.streamStop, BandProtocol.mask(stopping)) }
        if !start.isEmpty { send(.streamStart, BandProtocol.mask(start)) }
    }
}
