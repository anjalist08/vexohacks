import Foundation

/// The team's band. The kit's rule: one number, in one place, and never any other band.
enum BandConfig {
    static let number = 80
    static var name: String { String(format: "Vexo-HACK-%02d", number) }
}

/// The Vexo Open band's byte protocol (vexo-open-kit/contract/contract.md, v1.1): little-endian,
/// one frame per Bluetooth write / notification, `[type][body]`.
enum BandProtocol {
    static let service = "254f0001-df82-4a9c-a2b5-563a0f6b2021"
    static let rx = "254f0002-df82-4a9c-a2b5-563a0f6b2021"   // phone -> band (write)
    static let tx = "254f0003-df82-4a9c-a2b5-563a0f6b2021"   // band -> phone (notify)

    enum Op: UInt8 {
        case getInfo = 0x01, streamStart = 0x10, streamStop = 0x11, streamSetInterval = 0x13
        case imuSet = 0x20, ledSet = 0x50, tempSetInterval = 0x60
    }

    enum Stream: Int { case motion = 0, event = 1, activity = 2, audio = 3, battery = 4, temp = 5 }

    enum Frame: Equatable {
        case response(seq: UInt8, opcode: UInt8, status: UInt8, data: [UInt8])
        case notice(code: UInt8, arg: UInt8)
        case motion(tMs: UInt32, periodMs: UInt8, samples: [[Double]])     // ax ay az (g), gx gy gz (deg/s)
        case event(tMs: UInt32, kind: String, arg: UInt8)
        case activity(tMs: UInt32, steps: UInt32, cadence: UInt8, state: String, motionG: Double)
        case audio(seq: UInt16, opus: [UInt8])
        case battery(percent: UInt8, state: String, millivolts: UInt16)
        case temp(tMs: UInt32, celsius: Double)
        case other(type: UInt8)
    }

    // MARK: encoding

    static func command(seq: UInt8, _ op: Op, _ args: [UInt8] = []) -> [UInt8] {
        [0x01, seq, op.rawValue] + args
    }

    static func u16(_ v: Int) -> [UInt8] { [UInt8(v & 0xff), UInt8((v >> 8) & 0xff)] }
    static func u32(_ v: Int) -> [UInt8] { u16(v & 0xffff) + u16((v >> 16) & 0xffff) }

    static func mask(_ streams: [Stream]) -> [UInt8] { u16(streams.reduce(0) { $0 | (1 << $1.rawValue) }) }

    /// LED_SET args from the app's "#rrggbb", brightness 0..1, pattern name, period in ms.
    static func ledArgs(color: String, brightness: Double, pattern: String, periodMs: Int) -> [UInt8] {
        let hex = color.trimmingCharacters(in: CharacterSet(charactersIn: "#"))
        let v = Int(hex, radix: 16) ?? 0xffffff
        let codes = ["off": 0, "solid": 1, "blink": 2, "breathe": 3, "flash": 4, "rainbow": 5]
        let b = UInt8(max(0, min(255, Int((brightness * 255).rounded()))))
        let period = max(100, min(10000, periodMs))
        return [UInt8((v >> 16) & 0xff), UInt8((v >> 8) & 0xff), UInt8(v & 0xff), b,
                UInt8(codes[pattern] ?? 1)] + u16(period)
    }

    // MARK: decoding

    private static func u16(_ b: [UInt8], _ i: Int) -> UInt16 { UInt16(b[i]) | UInt16(b[i + 1]) << 8 }
    private static func i16(_ b: [UInt8], _ i: Int) -> Int16 { Int16(bitPattern: u16(b, i)) }
    private static func u32(_ b: [UInt8], _ i: Int) -> UInt32 {
        UInt32(b[i]) | UInt32(b[i + 1]) << 8 | UInt32(b[i + 2]) << 16 | UInt32(b[i + 3]) << 24
    }

    static let eventNames = [1: "tap", 2: "double-tap", 3: "free-fall", 4: "tilt", 5: "orientation",
                             6: "motion-start", 7: "motion-stop"]

    static func parse(_ f: [UInt8]) -> Frame? {
        guard let type = f.first else { return nil }
        let b = Array(f.dropFirst())
        switch type {
        case 0x02 where b.count >= 3:
            return .response(seq: b[0], opcode: b[1], status: b[2], data: Array(b.dropFirst(3)))
        case 0x03 where b.count >= 2:
            return .notice(code: b[0], arg: b[1])
        case 0x10 where b.count >= 6:
            let count = Int(b[5])
            guard b.count >= 6 + count * 12 else { return nil }
            let samples = (0..<count).map { i -> [Double] in
                let o = 6 + i * 12
                return [Double(i16(b, o)) / 1000, Double(i16(b, o + 2)) / 1000, Double(i16(b, o + 4)) / 1000,
                        Double(i16(b, o + 6)) / 10, Double(i16(b, o + 8)) / 10, Double(i16(b, o + 10)) / 10]
            }
            return .motion(tMs: u32(b, 0), periodMs: b[4], samples: samples)
        case 0x11 where b.count >= 6:
            return .event(tMs: u32(b, 0), kind: eventNames[Int(b[4])] ?? "unknown", arg: b[5])
        case 0x12 where b.count >= 12:
            let states = ["still", "walk", "run"]
            return .activity(tMs: u32(b, 0), steps: u32(b, 4), cadence: b[8],
                             state: Int(b[9]) < states.count ? states[Int(b[9])] : "still",
                             motionG: Double(u16(b, 10)) / 1000)
        case 0x13 where b.count >= 3:
            let len = Int(b[2])
            guard b.count >= 3 + len else { return nil }
            return .audio(seq: u16(b, 0), opus: Array(b[3..<(3 + len)]))
        case 0x14 where b.count >= 4:
            let states = ["battery", "charging", "charged"]
            return .battery(percent: b[0], state: Int(b[1]) < states.count ? states[Int(b[1])] : "battery",
                            millivolts: u16(b, 2))
        case 0x15 where b.count >= 8:
            return .temp(tMs: u32(b, 0), celsius: Double(Int32(bitPattern: u32(b, 4))) / 1000)
        default:
            return .other(type: type)
        }
    }

    /// GET_INFO response data -> the band number it reports (bytes 6-7).
    static func bandNumber(fromInfo data: [UInt8]) -> Int? {
        data.count >= 16 ? Int(u16(data, 6)) : nil
    }

    /// The band number in the advertising packet's manufacturer data: company 0xFFFF, then
    /// [0x4F][proto_major][band_no u16].
    static func bandNumber(fromManufacturerData d: [UInt8]) -> Int? {
        guard d.count >= 6, d[0] == 0xff, d[1] == 0xff, d[2] == 0x4f else { return nil }
        return Int(u16(d, 4))
    }
}
