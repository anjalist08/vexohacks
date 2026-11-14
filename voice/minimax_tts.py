"""MiniMax text-to-speech: the backup voice when ElevenLabs is unavailable.

ElevenLabs stays the main voice (it is the ElevenLabs sponsor track). MiniMax only speaks
when ElevenLabs has no key, fails or times out; after it come macOS `say` and print.

API: POST https://api.minimax.io/v1/t2a_v2 (non-streaming), audio returned hex-encoded in
`data.audio`, success when `base_resp.status_code == 0`.

Rules enforced here, the same as voice/elevenlabs_tts.py:
- Reads `VEXO_MINIMAX_API_KEY` via `keys.get("minimax", required=False)` after `keys.prepare()`.
- Sends the key only in the `Authorization: Bearer` header, never in a URL.
- Blocks HTTP redirects so the header is never forwarded elsewhere.
- Reports only status numbers on error, never keys or the service's error text.
"""
import binascii
import json
import ssl
import urllib.error
import urllib.request
from typing import Optional

import config
import keys

API_URL = "https://api.minimax.io/v1/t2a_v2"
DEFAULT_TIMEOUT = 20.0
MAX_AUDIO_BYTES = 20000000


class MiniMaxError(Exception):
    """Raised when MiniMax synthesis fails safely."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse all HTTP redirects so the Authorization header never leaves api.minimax.io."""

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


def request_body(text: str, voice_id: Optional[str] = None, model: Optional[str] = None) -> dict:
    """The JSON body for one non-streaming MP3 synthesis."""
    return {
        "model": model or config.MINIMAX_TTS_MODEL,
        "text": text,
        "stream": False,
        "output_format": "hex",
        "language_boost": "English",
        "voice_setting": {
            "voice_id": voice_id or config.MINIMAX_VOICE_ID,
            "speed": 1,
            "vol": 1,
            "pitch": 0,
            "emotion": "calm",
        },
        "audio_setting": {"sample_rate": 32000, "bitrate": 128000, "format": "mp3", "channel": 1},
    }


def synthesize_mp3(
    text: str,
    voice_id: Optional[str] = None,
    model: Optional[str] = None,
    api_key: Optional[str] = None,
    opener=None,
    timeout: float = DEFAULT_TIMEOUT,
) -> bytes:
    """Fetch synthesized MP3 bytes from MiniMax for `text`."""
    keys.prepare()
    clean_text = (text or "").strip()
    if not clean_text:
        raise MiniMaxError("Cannot synthesize empty text.")
    if len(clean_text) > 3000:
        raise MiniMaxError("Text too long for one non-streaming request.")

    secret = (api_key or "").strip() or keys.get("minimax", required=False)
    if not secret:
        raise MiniMaxError("Missing VEXO_MINIMAX_API_KEY.")
    if not secret.isascii() or not secret.isprintable() or " " in secret:
        raise MiniMaxError("VEXO_MINIMAX_API_KEY contains invalid characters.")

    if opener is None:
        opener = urllib.request.build_opener(_NoRedirect, urllib.request.HTTPSHandler(context=_ssl_context()))

    req = urllib.request.Request(
        API_URL,
        data=json.dumps(request_body(clean_text, voice_id, model)).encode("utf-8"),
        headers={"Authorization": "Bearer " + secret, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with opener.open(req, timeout=timeout) as resp:
            raw = resp.read(MAX_AUDIO_BYTES * 2 + 100000)
    except urllib.error.HTTPError as err:
        raise MiniMaxError("MiniMax request failed (HTTP status %d)." % err.code) from None
    except ssl.SSLCertVerificationError:
        raise MiniMaxError("SSL certificate check failed for api.minimax.io.") from None
    except OSError:
        raise MiniMaxError("Could not reach MiniMax API.") from None

    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise MiniMaxError("MiniMax returned a response that is not JSON.") from None
    status = (payload.get("base_resp") or {}).get("status_code")
    if status != 0:
        code = status if isinstance(status, int) else -1
        raise MiniMaxError("MiniMax refused the request (status code %d)." % code)
    audio_hex = (payload.get("data") or {}).get("audio") or ""
    try:
        audio = binascii.unhexlify(audio_hex)
    except (binascii.Error, TypeError):
        raise MiniMaxError("MiniMax returned audio that is not hex.") from None
    if not audio:
        raise MiniMaxError("MiniMax returned empty audio data.")
    if len(audio) > MAX_AUDIO_BYTES:
        raise MiniMaxError("MiniMax returned too much audio.")
    return audio
