"""Build the Wayback Trail commercial: narration, music bed and the final MP4.

    python3 commercial/build.py audio    # music bed + ElevenLabs narration (River) -> commercial/audio/
    python3 commercial/build.py video    # render frames (node render.mjs) and mux -> commercial/out/*.mp4
    python3 commercial/build.py all
    python3 commercial/build.py snapshot "Short title" "change one" "change two"
                                         # copy the current MP4 into demo-versions/ as the next version

The ElevenLabs key is read only through keys.py (VEXO_ELEVENLABS_API_KEY) and sent in
the xi-api-key header, as voice/elevenlabs_tts.py does. With no key, the request still
goes out without one, so a proxy that injects the key also works. If narration cannot be
made, the music bed is used on its own and the page falls back to the browser's voice.
"""
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
import wave

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import config  # noqa: E402
import keys    # noqa: E402

AUDIO = os.path.join(HERE, "audio")
OUT = os.path.join(HERE, "out")
SR = 44100
DURATION = 60.0

# id, preferred start (s), latest end (s: the scene it belongs to ends), line.
# Keep in sync with VO in index.html; timing.json written here overrides the page's times.
LINES = [
    ("vo1", 0.9, 5.3, "Every place you go leaves a trail."),
    ("vo2", 6.1, 12.9, "Say, \"remember this as the entrance.\" Wayback Trail pins it to the path you actually walked."),
    ("vo3a", 13.6, 17.8, "Every step counted. Every turn mapped."),
    ("vo3b", 17.9, 22.3, "Every time you ask, the Wayback app buzzes until you face the right way."),
    ("vo4a", 22.5, 25.0, "Can't see? It talks you through every turn."),
    ("vo4b", 25.0, 27.8, "Can't hear? The band glows, and the app buzzes."),
    ("vo4c", 27.4, 30.8, "Can't speak? Just tap, and type."),
    ("vo5", 31.5, 35.8, "In the crowd."),
    ("vo6", 36.6, 41.8, "In places you've never been."),
    ("vo7", 42.6, 47.8, "And places no one else is."),
    ("vo8", 48.6, 54.8, "Across the country. Around the world. The way back is always with you."),
    ("vo9", 56.0, 59.6, "This is the Wayback Trail."),
]


def tts(text, path):
    keys.prepare()
    key = keys.get("elevenlabs", required=False)
    url = "https://api.elevenlabs.io/v1/text-to-speech/%s?output_format=mp3_44100_128" % config.ELEVENLABS_VOICE_ID
    headers = {"Content-Type": "application/json", "Accept": "audio/mpeg"}
    if key:
        headers["xi-api-key"] = key
    body = {"text": text, "model_id": "eleven_multilingual_v2",
            "voice_settings": {"stability": 0.55, "similarity_boost": 0.8, "style": 0.2}}
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers)
    with urllib.request.urlopen(req, timeout=60) as r:
        data = r.read()
    with open(path, "wb") as f:
        f.write(data)


def duration(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "csv=p=0", path], capture_output=True, text=True, check=True)
    return float(out.stdout.strip())


def music_bed(path):
    """A quiet, warm pad (Fmaj7 - Am7 - Dm9 - Bbmaj7 - Fmaj9) with soft plucks and a
    low thump on every scene change. Synthesised here, so there are no licensing issues."""
    t = np.arange(int(SR * DURATION)) / SR
    hz = lambda n: 440.0 * 2 ** ((n - 69) / 12.0)
    chords = [(0, [53, 57, 60, 64]), (12, [57, 60, 64, 67]), (24, [50, 57, 60, 64]),
              (36, [46, 53, 57, 62]), (48, [53, 57, 60, 67]), (55, [41, 53, 60, 64, 69])]
    pad = np.zeros_like(t)
    for i, (start, notes) in enumerate(chords):
        end = chords[i + 1][0] if i + 1 < len(chords) else DURATION
        env = np.clip((t - start + 1.5) / 3.0, 0, 1) * np.clip((end + 1.5 - t) / 3.0, 0, 1)
        for n in notes:
            f = hz(n)
            pad += env * (np.sin(2 * np.pi * f * t) + .35 * np.sin(2 * np.pi * f * 2.003 * t)) * (.5 + .5 * np.sin(2 * np.pi * .11 * t + n))
    pad *= .035
    plucks = np.zeros_like(t)
    arp = [77, 81, 84, 88, 84, 81]
    for k, s in enumerate(np.arange(13.0, 48.0, 0.5)):
        n = arp[k % len(arp)] - (5 if 24 <= s < 36 else 0)
        i0 = int(s * SR); seg = t[: int(SR * 1.2)]
        tone = np.sin(2 * np.pi * hz(n) * seg) * np.exp(-seg * 5.5) * .05
        plucks[i0:i0 + len(seg)] += tone[: len(plucks) - i0]
    thumps = np.zeros_like(t)
    for b in [5.5, 13, 22, 31, 36, 42, 48, 55]:
        i0 = int((b - .05) * SR); seg = t[: int(SR * .6)]
        thumps[i0:i0 + len(seg)] += np.sin(2 * np.pi * (55 + 40 * np.exp(-seg * 20)) * seg) * np.exp(-seg * 7) * .22
    mix = pad + plucks + thumps
    mix *= np.clip(t / 1.0, 0, 1) * np.clip((DURATION - t) / 1.5, 0, 1)
    mix = np.tanh(mix * 1.4) / 1.4
    stereo = np.stack([mix, np.roll(mix, int(SR * .012))], axis=1)
    pcm = (np.clip(stereo, -1, 1) * 32767).astype("<i2")
    with wave.open(path, "wb") as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR); w.writeframes(pcm.tobytes())


def build_audio():
    os.makedirs(AUDIO, exist_ok=True)
    bed = os.path.join(AUDIO, "music.wav")
    music_bed(bed)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", bed, "-b:a", "160k", os.path.join(AUDIO, "music.mp3")], check=True)
    clips, failed = [], None
    for vid, start, _end, line in LINES:
        p = os.path.join(AUDIO, vid + ".mp3")
        try:
            tts(line, p)
        except urllib.error.HTTPError as e:
            failed = "ElevenLabs answered HTTP %d" % e.code
            break
        except OSError as e:
            failed = "ElevenLabs unreachable (%s)" % type(e).__name__
            break
        clips.append((vid, start, _end, p, duration(p)))
    if failed:
        print("Narration not made: %s. Using the music bed alone; the page falls back to the browser voice." % failed)
        for name in ("narration.mp3", "timing.json"):
            if os.path.exists(os.path.join(AUDIO, name)):
                os.remove(os.path.join(AUDIO, name))
        return False
    # schedule: preferred start, never overlapping the previous line, warn if past its scene
    timing, cursor = [], 0.0
    for vid, start, end, p, d in clips:
        s = max(start, cursor + .2)
        if s + d > end:
            print("  note: %s runs %.1f s past its scene" % (vid, s + d - end))
        timing.append({"id": vid, "t": round(s, 2), "d": round(d, 2)})
        cursor = s + d
    with open(os.path.join(AUDIO, "timing.json"), "w") as f:
        json.dump({"voice": "ElevenLabs " + config.ELEVENLABS_VOICE_ID, "vo": timing}, f, indent=1)
    cmd = ["ffmpeg", "-v", "error", "-y", "-i", bed]
    for c in clips:
        cmd += ["-i", c[3]]
    parts, labels = [], []
    for i, tm in enumerate(timing):
        ms = int(tm["t"] * 1000)
        parts.append("[%d:a]aresample=44100,pan=stereo|c0=c0|c1=c0,volume=1.6,adelay=%d|%d[v%d]" % (i + 1, ms, ms, i))
        labels.append("[v%d]" % i)
    # duck the music under the voice
    parts.append("%samix=inputs=%d:normalize=0[vo]" % ("".join(labels), len(labels)))
    parts.append("[vo]asplit[vo1][vo2]")
    parts.append("[0:a][vo1]sidechaincompress=threshold=0.03:ratio=6:attack=20:release=400[bed]")
    parts.append("[bed][vo2]amix=inputs=2:normalize=0,atrim=0:60,alimiter=limit=0.95[out]")
    cmd += ["-filter_complex", ";".join(parts), "-map", "[out]", "-b:a", "192k", os.path.join(AUDIO, "narration.mp3")]
    subprocess.run(cmd, check=True)
    print("Narration ready:", ", ".join("%s@%.1fs" % (x["id"], x["t"]) for x in timing))
    return True


def build_video():
    subprocess.run(["node", os.path.join(HERE, "render.mjs"), "frames", "30"], check=True, cwd=HERE)
    audio = os.path.join(AUDIO, "narration.mp3")
    if not os.path.exists(audio):
        audio = os.path.join(AUDIO, "music.mp3")
    out = os.path.join(OUT, "wayback-trail-commercial.mp4")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-framerate", "30", "-i", os.path.join(OUT, "frames", "%05d.png"),
                    "-i", audio, "-c:v", "libx264", "-preset", "slow", "-crf", "18", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-b:a", "192k", "-t", "60", "-movflags", "+faststart", out], check=True)
    print("Video:", out, "(%.1f s)" % duration(out))


VERSIONS = os.path.join(os.path.dirname(HERE), "demo-versions")


def write_versions_readme(versions):
    lines = ["# Demo versions", "",
             "Every rendered cut of the 60-second Wayback Trail x Vexo commercial and the working demo, so each iteration",
             "can be tracked and watched. Open the `.mp4` files directly, or serve this folder and",
             "open `index.html` to see them all with their change notes:", "",
             "    cd demo-versions && python3 -m http.server 8090   # then http://localhost:8090", "",
             "Add the next version after a render with",
             "`python3 commercial/build.py snapshot \"Title\" \"change\" ...`. That copies",
             "`commercial/out/wayback-trail-commercial.mp4` here, makes a thumbnail, and updates",
             "`versions.json` and this file.", "",
             "| Version | Date | Commit | File | What changed |", "| --- | --- | --- | --- | --- |"]
    for v in sorted(versions, key=lambda v: -v["version"]):
        lines.append("| %s: %s | %s | `%s` | [%s](%s) | %s |" % (
            v.get("label") or "v%d" % v["version"], v["title"], v["date"], v["commit"], v["file"], v["file"].replace(" ", "%20"),
            "<br>".join(c.replace("|", "\\|") for c in v["changes"])))
    with open(os.path.join(VERSIONS, "README.md"), "w") as f:
        f.write("\n".join(lines) + "\n")


def snapshot(title, changes):
    import datetime
    import re
    src = os.path.join(OUT, "wayback-trail-commercial.mp4")
    path = os.path.join(VERSIONS, "versions.json")
    versions = json.load(open(path)) if os.path.exists(path) else []
    n = max([v["version"] for v in versions] or [0]) + 1
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-") or "cut"
    name = "v%d-%s.mp4" % (n, slug)
    os.makedirs(os.path.join(VERSIONS, "thumbs"), exist_ok=True)
    import shutil
    shutil.copyfile(src, os.path.join(VERSIONS, name))
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", "39.5", "-i", src, "-frames:v", "1", "-vf", "scale=640:-1",
                    os.path.join(VERSIONS, "thumbs", name[:-4] + ".jpg")], check=True)
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
                            cwd=HERE).stdout.strip()
    versions.append({"version": n, "file": name, "date": datetime.date.today().isoformat(),
                     "commit": commit, "title": title, "changes": list(changes)})
    with open(path, "w") as f:
        json.dump(versions, f, indent=1, ensure_ascii=False)
        f.write("\n")
    write_versions_readme(versions)
    print("Saved demo-versions/%s as v%d" % (name, n))


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "snapshot":
        if len(sys.argv) < 3:
            raise SystemExit('usage: build.py snapshot "Title" ["change" ...]')
        snapshot(sys.argv[2], sys.argv[3:])
        raise SystemExit(0)
    if len(sys.argv) > 1 and sys.argv[1] == "readme":
        write_versions_readme(json.load(open(os.path.join(VERSIONS, "versions.json"))))
        raise SystemExit(0)
    what = sys.argv[1] if len(sys.argv) > 1 else "all"
    if what in ("audio", "all"):
        build_audio()
    if what in ("video", "all"):
        build_video()
