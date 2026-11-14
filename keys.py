"""API keys, read in one place. Every key has a VEXO_ name on purpose.

Teammates' laptops can also hold personal GEMINI_API_KEY / OPENAI_API_KEY variables,
and SDKs (google-genai, Pipecat, the kit's ai.py) pick those up by themselves when no
key is passed. An environment variable also wins over .env. So this project:

- reads only the VEXO_ names below (environment first, then .env next to this file);
- removes the generic names from this process at start-up (keys.prepare()), so no
  library can fall back to a personal key;
- passes every key explicitly (api_key=keys.get("gemini"), and so on).

Never print, log or commit a key.
"""
import os

NAMES = {
    "gemini": "VEXO_GEMINI_API_KEY",
    "deepgram": "VEXO_DEEPGRAM_API_KEY",
    "elevenlabs": "VEXO_ELEVENLABS_API_KEY",
}

# Generic names that libraries read by themselves. Removed from this process only.
GENERIC = ("GEMINI_API_KEY", "GOOGLE_API_KEY", "OPENAI_API_KEY",
           "DEEPGRAM_API_KEY", "ELEVENLABS_API_KEY", "ELEVEN_API_KEY")

ENV_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")


def _from_file(name: str, path: str = None) -> str:
    path = path or ENV_FILE
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("export "):
                    line = line[7:]
                key, _, value = line.partition("=")
                if key.strip() == name and value.strip():
                    return value.strip().strip("'\"")
    except OSError:
        pass
    return ""


def get(service: str, required: bool = True) -> str:
    """The key for "gemini", "deepgram" or "elevenlabs". Never print what this returns."""
    name = NAMES[service]
    found = os.environ.get(name, "").strip() or _from_file(name)
    if not found and required:
        raise SystemExit("Missing %s. Set it in your shell (export %s=...) or in .env "
                         "(see .env.example)." % (name, name))
    return found


def prepare() -> None:
    """Call once at start-up, before importing any AI SDK or the kit's speech module.

    Drops the generic key names from this process, then sets DEEPGRAM_API_KEY from
    VEXO_DEEPGRAM_API_KEY, because the kit's speech.py only reads that name."""
    for name in GENERIC:
        os.environ.pop(name, None)
    deepgram = get("deepgram", required=False)
    if deepgram:
        os.environ["DEEPGRAM_API_KEY"] = deepgram
