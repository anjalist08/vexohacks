"""ElevenLabs text-to-speech on the laptop speaker, with safe local fallbacks.

Rules enforced here:
- Reads `VEXO_ELEVENLABS_API_KEY` via `keys.get("elevenlabs", required=False)` after `keys.prepare()`.
- Sends key in the `xi-api-key` HTTP header, NEVER in a URL query string.
- Blocks HTTP redirects (`_NoRedirect`) so the header is never forwarded elsewhere.
- Shows only HTTP status numbers on error, never keys or untrusted error payloads.
- Always deletes temporary MP3 files in `finally:`.
- Falls back cleanly to macOS `say`, and then terminal `print("    [SAY] ...")`.
"""
import json
import os
import shutil
import ssl
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable, Optional

import config
import keys

API_BASE = "https://api.elevenlabs.io/v1/text-to-speech"
DEFAULT_MODEL_ID = "eleven_turbo_v2_5"
DEFAULT_TIMEOUT = 20.0


class ElevenLabsError(Exception):
    """Raised when ElevenLabs synthesis or local MP3 playback fails safely."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse all HTTP redirects so `xi-api-key` never leaves the ElevenLabs endpoint."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _ssl_context() -> ssl.SSLContext:
    context = ssl.create_default_context()
    try:
        import certifi
        context.load_verify_locations(certifi.where())
    except ImportError:
        pass
    return context


def default_play_mp3(path: str) -> None:
    """Play an MP3 file on the laptop speaker using a standard local audio player."""
    if shutil.which("afplay"):
        subprocess.run(["afplay", path], check=True)
        return
    if shutil.which("mpg123"):
        subprocess.run(["mpg123", "-q", path], check=True)
        return
    if shutil.which("ffplay"):
        subprocess.run(
            ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", path],
            check=True,
        )
        return
    raise ElevenLabsError("No local MP3 player (afplay/mpg123/ffplay) found.")


def synthesize_mp3(
    text: str,
    voice_id: Optional[str] = None,
    model_id: str = DEFAULT_MODEL_ID,
    api_key: Optional[str] = None,
    opener=None,
    timeout: float = DEFAULT_TIMEOUT,
) -> bytes:
    """Fetch synthesized MP3 bytes from ElevenLabs for `text`."""
    keys.prepare()
    clean_text = (text or "").strip()
    if not clean_text:
        raise ElevenLabsError("Cannot synthesize empty text.")

    resolved_voice = (voice_id if voice_id is not None else config.ELEVENLABS_VOICE_ID) or ""
    resolved_voice = str(resolved_voice).strip()
    if not resolved_voice:
        raise ElevenLabsError("ELEVENLABS_VOICE_ID is not configured.")

    secret = (api_key or "").strip() or keys.get("elevenlabs", required=False)
    if not secret:
        raise ElevenLabsError("Missing VEXO_ELEVENLABS_API_KEY.")
    if not secret.isascii() or not secret.isprintable() or " " in secret:
        raise ElevenLabsError("VEXO_ELEVENLABS_API_KEY contains invalid characters.")

    url = "%s/%s" % (API_BASE, urllib.parse.quote(resolved_voice, safe=""))
    body = {
        "text": clean_text,
        "model_id": model_id,
    }

    if opener is None:
        opener = urllib.request.build_opener(
            _NoRedirect,
            urllib.request.HTTPSHandler(context=_ssl_context()),
        )

    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "xi-api-key": secret,
            "Accept": "audio/mpeg",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with opener.open(req, timeout=timeout) as resp:
            audio_bytes = resp.read(20000000)
    except urllib.error.HTTPError as err:
        raise ElevenLabsError(
            "ElevenLabs request failed (HTTP status %d)." % err.code
        ) from None
    except ssl.SSLCertVerificationError:
        raise ElevenLabsError(
            "SSL certificate check failed for api.elevenlabs.io."
        ) from None
    except OSError:
        raise ElevenLabsError("Could not reach ElevenLabs API.") from None

    if not audio_bytes:
        raise ElevenLabsError("ElevenLabs returned empty audio data.")
    return audio_bytes


class ElevenLabsSpeaker:
    """Callable speaker (`app.speak = ElevenLabsSpeaker()`) with `say` and `print` fallbacks."""

    def __init__(
        self,
        voice_id: Optional[str] = None,
        model_id: str = DEFAULT_MODEL_ID,
        api_key: Optional[str] = None,
        opener=None,
        player: Optional[Callable[[str], None]] = None,
        allow_macos_say: bool = True,
        say_runner: Optional[Callable[[str], None]] = None,
        on_say: Optional[Callable[[str], None]] = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        keys.prepare()
        self.voice_id = voice_id
        self.model_id = model_id
        self._api_key = api_key
        self.opener = opener
        self.player = player or default_play_mp3
        self.allow_macos_say = allow_macos_say
        self.say_runner = say_runner
        self.on_say = on_say
        self.timeout = timeout

    def __call__(self, text: str) -> str:
        return self.speak(text)

    def speak(self, text: str) -> str:
        """Speak `text` and return backend used: `'elevenlabs'`, `'macos_say'`, `'print'`, or `'none'`."""
        clean = (text or "").strip()
        if not clean:
            return "none"

        if self.on_say is not None:
            self.on_say(clean)
        else:
            print("    [SAY] %s" % clean)

        keys.prepare()
        secret = (self._api_key or "").strip() or keys.get("elevenlabs", required=False)
        if secret:
            try:
                mp3_bytes = synthesize_mp3(
                    text=clean,
                    voice_id=self.voice_id,
                    model_id=self.model_id,
                    api_key=secret,
                    opener=self.opener,
                    timeout=self.timeout,
                )
                self._play_temp_mp3(mp3_bytes)
                return "elevenlabs"
            except (ElevenLabsError, subprocess.SubprocessError, OSError) as exc:
                msg = str(exc) if isinstance(exc, ElevenLabsError) else exc.__class__.__name__
                print("    [TTS] ElevenLabs unavailable (%s); falling back." % msg, file=sys.stderr)

        if self._try_macos_say(clean):
            return "macos_say"

        return "print"

    def _play_temp_mp3(self, mp3_bytes: bytes) -> None:
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
                tmp.write(mp3_bytes)
                tmp_path = tmp.name
            self.player(tmp_path)
        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass

    def _try_macos_say(self, text: str) -> bool:
        if not self.allow_macos_say:
            return False
        if self.say_runner is not None:
            try:
                self.say_runner(text)
                return True
            except Exception:
                return False
        if not shutil.which("say"):
            return False
        safe_text = (" " + text) if text.startswith("-") else text
        try:
            subprocess.run(["say", safe_text], check=True)
            return True
        except (subprocess.SubprocessError, OSError):
            return False


def speak(text: str, **kwargs) -> str:
    """Convenience one-shot wrapper around `ElevenLabsSpeaker`."""
    return ElevenLabsSpeaker(**kwargs).speak(text)
