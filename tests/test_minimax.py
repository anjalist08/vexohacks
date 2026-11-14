"""MiniMax backup voice: request shape, key handling, errors, and the fallback order.
No network: every request goes to a fake opener."""
import io
import json
import os
import sys
import unittest
import urllib.error
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import keys  # noqa: E402
from voice import minimax_tts  # noqa: E402
from voice.elevenlabs_tts import ElevenLabsSpeaker  # noqa: E402

KEY = "test-vexo-minimax-token"


class Resp:
    def __init__(self, body: bytes):
        self._buf = io.BytesIO(body)

    def read(self, n=-1):
        return self._buf.read(n)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class Opener:
    def __init__(self, responder):
        self.responder, self.requests = responder, []

    def open(self, req, timeout=None):
        self.requests.append(req)
        return self.responder(req)


def ok_body(audio=b"ID3fake-mp3"):
    return json.dumps({"data": {"audio": audio.hex(), "status": 2},
                       "base_resp": {"status_code": 0, "status_msg": "success"}}).encode()


def http_error(code):
    def raise_it(req):
        raise urllib.error.HTTPError(req.full_url, code, "error", {}, None)
    return raise_it


class MiniMaxSynthesisTests(unittest.TestCase):
    def test_request_shape_and_hex_decoding(self):
        opener = Opener(lambda req: Resp(ok_body(b"ID3abc")))
        audio = minimax_tts.synthesize_mp3("Turn left now.", api_key=KEY, opener=opener)
        self.assertEqual(audio, b"ID3abc")
        req = opener.requests[0]
        self.assertEqual(req.full_url, "https://api.minimax.io/v1/t2a_v2")
        self.assertEqual(req.get_header("Authorization"), "Bearer " + KEY)
        self.assertNotIn(KEY, req.full_url)
        body = json.loads(req.data)
        self.assertEqual(body["text"], "Turn left now.")
        self.assertFalse(body["stream"])
        self.assertEqual(body["output_format"], "hex")
        self.assertEqual(body["audio_setting"]["format"], "mp3")
        self.assertTrue(body["voice_setting"]["voice_id"])

    def test_service_error_code_is_reported_without_its_text(self):
        body = json.dumps({"base_resp": {"status_code": 1004, "status_msg": "secret detail " + KEY}}).encode()
        with self.assertRaises(minimax_tts.MiniMaxError) as e:
            minimax_tts.synthesize_mp3("hi", api_key=KEY, opener=Opener(lambda req: Resp(body)))
        self.assertIn("1004", str(e.exception))
        self.assertNotIn(KEY, str(e.exception))
        self.assertNotIn("secret detail", str(e.exception))

    def test_http_error_reports_status_only(self):
        with self.assertRaises(minimax_tts.MiniMaxError) as e:
            minimax_tts.synthesize_mp3("hi", api_key=KEY, opener=Opener(http_error(401)))
        self.assertIn("401", str(e.exception))

    def test_bad_audio_and_missing_key(self):
        bad = json.dumps({"data": {"audio": "zz-not-hex"}, "base_resp": {"status_code": 0}}).encode()
        with self.assertRaises(minimax_tts.MiniMaxError):
            minimax_tts.synthesize_mp3("hi", api_key=KEY, opener=Opener(lambda req: Resp(bad)))
        with mock.patch.dict(os.environ, {"MINIMAX_API_KEY": "personal"}, clear=True), \
                mock.patch.object(keys, "ENV_FILE", "/nonexistent/.env"):
            with self.assertRaises(minimax_tts.MiniMaxError):        # generic name is never used
                minimax_tts.synthesize_mp3("hi", opener=Opener(lambda req: Resp(ok_body())))


def read_file(path):
    with open(path, "rb") as f:
        return f.read()


class FallbackOrderTests(unittest.TestCase):
    def speaker(self, eleven_opener, minimax_opener, played, said, minimax_key=KEY):
        return ElevenLabsSpeaker(api_key="test-vexo-xi-token", opener=eleven_opener,
                                 minimax_api_key=minimax_key, minimax_opener=minimax_opener,
                                 player=lambda path: played.append(read_file(path)),
                                 say_runner=said.append, on_say=lambda t: None)

    def test_elevenlabs_first(self):
        played, said = [], []
        mm = Opener(lambda req: Resp(ok_body()))
        s = self.speaker(Opener(lambda req: Resp(b"eleven-mp3")), mm, played, said)
        self.assertEqual(s("Route started."), "elevenlabs")
        self.assertEqual(played, [b"eleven-mp3"])
        self.assertEqual(mm.requests, [])

    def test_minimax_when_elevenlabs_fails(self):
        played, said = [], []
        s = self.speaker(Opener(http_error(500)), Opener(lambda req: Resp(ok_body(b"ID3mm"))), played, said)
        with mock.patch("sys.stderr", new_callable=io.StringIO):
            self.assertEqual(s("Turn right now."), "minimax")
        self.assertEqual(played, [b"ID3mm"])
        self.assertEqual(said, [])

    def test_macos_say_when_both_fail(self):
        played, said = [], []
        s = self.speaker(Opener(http_error(500)), Opener(http_error(503)), played, said)
        with mock.patch("sys.stderr", new_callable=io.StringIO):
            self.assertEqual(s("You have arrived."), "macos_say")
        self.assertEqual(said, ["You have arrived."])

    def test_no_minimax_key_skips_it(self):
        played, said = [], []
        mm = Opener(lambda req: Resp(ok_body()))
        with mock.patch.dict(os.environ, {}, clear=True), \
                mock.patch.object(keys, "ENV_FILE", "/nonexistent/.env"):
            s = self.speaker(Opener(http_error(500)), mm, played, said, minimax_key=None)
            with mock.patch("sys.stderr", new_callable=io.StringIO):
                self.assertEqual(s("Hello."), "macos_say")
        self.assertEqual(mm.requests, [])


if __name__ == "__main__":
    unittest.main()
