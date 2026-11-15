"""Build the 60-second working-demo video (simulated screen recording, honest about it).

    python3 demo-video/build.py plan     # simulate + voices + plan.json + audio mix
    python3 demo-video/build.py video    # render frames (node render.mjs) and mux -> out/wayback-working-demo.mp4
    python3 demo-video/build.py all

Everything the phone and the panels show comes from simulate.py, which runs the real Wayback
code (app.py, tracker/wrist.py, store/guidance.py, store/haptics.py) on a synthetic walk.
Voices are ElevenLabs: the walker (Chris), the app (River, config.ELEVENLABS_VOICE_ID) and a
narrator (Sarah). The key is read only through keys.py and sent in the xi-api-key header.
"""
import hashlib
import json
import os
import subprocess
import sys
import urllib.request
import wave

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)
import config  # noqa: E402
import keys    # noqa: E402

AUDIO = os.path.join(HERE, "audio")
OUT = os.path.join(HERE, "out")
SR = 44100
DURATION = 60.0
VOICES = {"walker": "iP95p4xoKVk53GoZ742B",            # Chris: the person wearing the band
          "app": config.ELEVENLABS_VOICE_ID,            # River: the voice Wayback speaks in
          "narrator": "EXAVITQu4vr4xnSDxMaL"}           # Sarah: the narrator
WALK_OUT_V = 10.0        # seconds of video for the outward walk (sped up, labelled on screen)


def tts(voice, text):
    os.makedirs(AUDIO, exist_ok=True)
    h = hashlib.sha1((voice + "|" + text).encode()).hexdigest()[:12]
    path = os.path.join(AUDIO, "%s-%s.mp3" % (voice, h))
    if not os.path.exists(path):
        keys.prepare()
        key = keys.get("elevenlabs", required=False)
        headers = {"Content-Type": "application/json", "Accept": "audio/mpeg"}
        if key:
            headers["xi-api-key"] = key
        body = {"text": text, "model_id": "eleven_multilingual_v2",
                "voice_settings": {"stability": 0.5, "similarity_boost": 0.8, "style": 0.15}}
        req = urllib.request.Request("https://api.elevenlabs.io/v1/text-to-speech/%s?output_format=mp3_44100_128" % VOICES[voice],
                                     data=json.dumps(body).encode(), headers=headers)
        with urllib.request.urlopen(req, timeout=60) as r:
            data = r.read()
        with open(path, "wb") as f:
            f.write(data)
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                         capture_output=True, text=True, check=True)
    return path, float(out.stdout.strip())


def plan():
    import simulate
    simulate.main()
    tl = json.load(open(os.path.join(HERE, "timeline.json")))
    ev = tl["events"]
    users = [e for e in ev if e["kind"] == "user"]
    says = [e for e in ev if e["kind"] == "say"]

    clips = []

    def clip(voice, text, at, kind, ref=None):
        path, d = tts(voice, text)
        c = {"voice": voice, "text": text, "t": round(at, 2), "d": round(d, 2), "file": os.path.basename(path), "kind": kind, "ref": ref}
        clips.append(c)
        return c

    def end(c, gap=0.0):
        return c["t"] + c["d"] + gap

    # the app's reply to each command is the say event at the same moment as the user event
    def reply_to(u):
        return next(s for s in says if s["t"] == u["t"] and ev.index(s) > ev.index(u))

    n1 = clip("narrator", "This is Wayback, running on a Vexo band and an iPhone.", 0.7, "narrator")
    n2 = clip("narrator", "The app finds the band. Double-tap it, and just talk.", max(4.7, end(n1, .4)), "narrator")
    cmd = {}
    w = clip("walker", "Start route.", max(9.2, end(n2, .5)), "user", 0)
    r = clip("app", reply_to(users[0])["text"], end(w, .45), "say", 0)
    cmd[0] = (w, r)
    w = clip("walker", "Remember this as the entrance.", end(r, .7), "user", 1)
    r = clip("app", reply_to(users[1])["text"], end(w, .45), "say", 1)
    cmd[1] = (w, r)
    walk_v = max(17.0, end(r, .5))
    n3 = clip("narrator", "Walk anywhere. Every step and turn becomes your trail.", walk_v + 1.4, "narrator")
    walk_end_v = walk_v + WALK_OUT_V
    w = clip("walker", "Remember this as the elevator.", walk_end_v + .3, "user", 2)
    r = clip("app", reply_to(users[2])["text"], end(w, .45), "say", 2)
    cmd[2] = (w, r)
    w = clip("walker", "Take me back to the entrance.", end(r, .6), "user", 3)
    r4 = clip("app", reply_to(users[3])["text"], end(w, .4), "say", 3)
    cmd[3] = (w, r4)
    nav_v = r4["t"]

    s_nav = users[3]["t"]
    arrived = [e for e in ev if e["kind"] == "say" and e["text"].startswith("You have reached")][-1]
    s_arr = arrived["t"]
    outro_v = 54.4
    rate = max(1.0, (s_arr - s_nav) / (outro_v - 3.0 - nav_v))      # >1 means sped up
    vt_back = lambda s: nav_v + (s - s_nav) / rate
    s_hold = s_arr + 0.15
    segments = [[0, walk_v, 0, 0], [walk_v, walk_end_v, 0, s_nav], [walk_end_v, nav_v, s_nav, s_nav],
                [nav_v, vt_back(s_hold), s_nav, s_hold], [vt_back(s_hold), DURATION, s_hold, s_hold]]

    def vt(s):
        for v0, v1, s0, s1 in segments:
            if s1 > s0 and s0 <= s <= s1:
                return v0 + (s - s0) * (v1 - v0) / (s1 - s0)
        return None

    # the replies spoken during the walk back ("Turn left…", "You have reached…")
    prev_end = end(r4, .2)
    for s in says:
        if s["t"] > s_nav:
            c = clip("app", s["text"], max(vt(s["t"]), prev_end), "say", None)
            c["sim_t"] = s["t"]
            prev_end = end(c, .2)
    n4 = clip("narrator", "Your voice in. The way back out. This is the Wayback Trail.", max(outro_v + .5, prev_end + .3), "narrator")

    # video-time events: commands at their spoken times, everything else on the time map
    vev = []
    for e in ev:
        e = dict(e)
        if e["kind"] == "phase":
            continue
        if e["kind"] == "user":
            k = users.index(next(u for u in users if u is e or (u["t"] == e["t"] and u["text"] == e["text"])))
            e["vt"] = cmd[k][0]["t"]
        elif e["t"] <= s_nav + 1e-6 and e["kind"] in ("tool", "say", "led", "landmark", "guidance"):
            # the response to the last command at or before this moment
            k = max(i for i, u in enumerate(users) if u["t"] <= e["t"] and ev.index(u) < ev.index(next(x for x in ev if x is e or x == e)))
            e["vt"] = cmd[k][1]["t"]
        else:
            e["vt"] = vt(e["t"])
            if e["kind"] == "say":
                c = next((c for c in clips if c.get("sim_t") == e["t"]), None)
                if c:
                    e["vt"] = c["t"]
        vev.append(e)
    vev.sort(key=lambda e: e["vt"])
    listen = [[cmd[k][0]["t"] - .7, end(cmd[k][0], .25)] for k in cmd]
    out = {"note": tl["note"], "segments": [[round(a, 3) for a in s] for s in segments],
           "walk_rate": round(s_nav / WALK_OUT_V, 2), "back_rate": round(rate, 2),
           "listen": listen, "events": vev, "clips": clips, "samples": tl["samples"],
           "outro": outro_v, "connect": [n2["t"], n2["t"] + 1.2]}
    with open(os.path.join(HERE, "plan.json"), "w") as f:
        json.dump(out, f)
    for c in sorted(clips, key=lambda c: c["t"]):
        print("%6.2f-%6.2f %-8s %s" % (c["t"], c["t"] + c["d"], c["voice"], c["text"]))
    print("segments", out["segments"], "walk x%.2f back x%.2f" % (out["walk_rate"], out["back_rate"]))
    mix(out)
    return out


PAT = {"wrong_left": [120, 120, 120], "wrong_right": [120, 120, 120, 120, 120], "on_track": [600], "tick": [50],
       "turn_soon": [80], "turn_left": [500, 150, 150], "turn_right": [500, 150, 150, 150, 150],
       "turn_around": [500, 150, 500], "arrived": [700, 200, 700, 200, 700], "lost": [100, 60] * 4 + [100]}


def mix(p):
    t = np.arange(int(SR * DURATION)) / SR
    hz = lambda n: 440.0 * 2 ** ((n - 69) / 12.0)
    # backing track: soft pulse pad, a little brighter than the commercial's
    chords = [(0, [57, 60, 64, 67]), (9, [53, 57, 60, 64]), (17, [55, 59, 62, 67]), (27, [52, 55, 59, 64]),
              (36, [57, 60, 64, 69]), (45, [53, 57, 60, 65]), (54, [48, 55, 60, 64, 67])]
    bed = np.zeros_like(t)
    for i, (s, notes) in enumerate(chords):
        e = chords[i + 1][0] if i + 1 < len(chords) else DURATION
        env = np.clip((t - s + 1) / 2, 0, 1) * np.clip((e + 1 - t) / 2, 0, 1)
        for n in notes:
            bed += env * np.sin(2 * np.pi * hz(n) * t) * (.55 + .45 * np.sin(2 * np.pi * .13 * t + n))
    bed *= .028
    pulse = np.zeros_like(t)
    for k, s in enumerate(np.arange(4.0, 54.0, .5)):
        i0 = int(s * SR); seg = t[: int(SR * .9)]
        note = [69, 72, 76, 79][k % 4]
        pulse[i0:i0 + len(seg)] += np.sin(2 * np.pi * hz(note) * seg) * np.exp(-seg * 7) * .022
    kick = np.zeros_like(t)
    for s in np.arange(17.0, 54.0, 1.0):
        i0 = int(s * SR); seg = t[: int(SR * .35)]
        kick[i0:i0 + len(seg)] += np.sin(2 * np.pi * (50 + 60 * np.exp(-seg * 30)) * seg) * np.exp(-seg * 12) * .09
    music = (bed + pulse + kick) * np.clip(t / 1.2, 0, 1) * np.clip((DURATION - t) / 1.5, 0, 1)
    # the iPhone's buzzes, made audible: a low motor hum in each pattern's "on" parts
    sfx = np.zeros_like(t)
    for e in p["events"]:
        if e["kind"] != "buzz" or e["vt"] is None:
            continue
        acc = 0.0
        for j, ms in enumerate(PAT.get(e["cue"], [])):
            if j % 2 == 0:
                i0 = int((e["vt"] + acc / 1000) * SR); n = int(ms / 1000 * SR)
                seg = t[:n]
                env = np.clip(seg / .01, 0, 1) * np.clip((ms / 1000 - seg) / .02, 0, 1)
                hum = (np.sin(2 * np.pi * 165 * seg) + .5 * np.sin(2 * np.pi * 330 * seg)) * env * (.10 if e["cue"] == "tick" else .2)
                sfx[i0:i0 + n] += hum[: max(0, len(sfx) - i0)]
            acc += ms
    def wav(path, x):
        st = np.stack([x, x], axis=1)
        with wave.open(path, "wb") as w:
            w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR)
            w.writeframes((np.clip(st, -1, 1) * 32767).astype("<i2").tobytes())
    wav(os.path.join(AUDIO, "music.wav"), np.tanh(music * 1.3) / 1.3)
    wav(os.path.join(AUDIO, "sfx.wav"), sfx)
    cmd = ["ffmpeg", "-v", "error", "-y", "-i", os.path.join(AUDIO, "music.wav"), "-i", os.path.join(AUDIO, "sfx.wav")]
    parts, labels = [], []
    for i, c in enumerate(p["clips"]):
        cmd += ["-i", os.path.join(AUDIO, c["file"])]
        ms = int(c["t"] * 1000)
        parts.append("[%d:a]aresample=44100,pan=stereo|c0=c0|c1=c0,volume=%s,adelay=%d|%d[v%d]" % (i + 2, "1.5", ms, ms, i))
        labels.append("[v%d]" % i)
    parts.append("%samix=inputs=%d:normalize=0[vo]" % ("".join(labels), len(labels)))
    parts.append("[vo]asplit[vo1][vo2]")
    parts.append("[0:a][vo1]sidechaincompress=threshold=0.03:ratio=6:attack=20:release=350[bed]")
    parts.append("[bed][1:a][vo2]amix=inputs=3:normalize=0,atrim=0:60,alimiter=limit=0.95[out]")
    cmd += ["-filter_complex", ";".join(parts), "-map", "[out]", "-b:a", "192k", os.path.join(AUDIO, "demo-audio.mp3")]
    subprocess.run(cmd, check=True)
    print("audio:", os.path.join(AUDIO, "demo-audio.mp3"))


def video():
    subprocess.run(["node", os.path.join(HERE, "render.mjs"), "frames", "30"], check=True, cwd=HERE)
    out = os.path.join(OUT, "wayback-working-demo.mp4")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-framerate", "30", "-i", os.path.join(OUT, "frames", "%05d.png"),
                    "-i", os.path.join(AUDIO, "demo-audio.mp3"), "-c:v", "libx264", "-preset", "slow", "-crf", "18",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-t", "60", "-movflags", "+faststart", out], check=True)
    print("video:", out)


if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else "all"
    if what in ("plan", "all"):
        plan()
    if what in ("video", "all"):
        video()
