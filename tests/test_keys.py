"""keys.py never falls back to a generic (possibly personal) key name."""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import keys  # noqa: E402


class KeyTests(unittest.TestCase):
    def test_prepare_drops_generic_names_and_maps_deepgram(self):
        env = {"GEMINI_API_KEY": "personal", "GOOGLE_API_KEY": "personal", "OPENAI_API_KEY": "personal",
               "VEXO_DEEPGRAM_API_KEY": "team-dg"}
        with mock.patch.dict(os.environ, env, clear=True):
            keys.prepare()
            for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "OPENAI_API_KEY"):
                self.assertNotIn(name, os.environ)
            self.assertEqual(os.environ["DEEPGRAM_API_KEY"], "team-dg")

    def test_get_ignores_generic_name(self):
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "personal"}, clear=True), \
                mock.patch.object(keys, "ENV_FILE", os.path.join(tempfile.gettempdir(), "no-such.env")):
            self.assertEqual(keys.get("gemini", required=False), "")
            with self.assertRaises(SystemExit):
                keys.get("gemini")

    def test_env_wins_then_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, ".env")
            with open(path, "w") as f:
                f.write("export VEXO_GEMINI_API_KEY='from-file'\n")
            with mock.patch.object(keys, "ENV_FILE", path):
                with mock.patch.dict(os.environ, {}, clear=True):
                    self.assertEqual(keys.get("gemini"), "from-file")
                with mock.patch.dict(os.environ, {"VEXO_GEMINI_API_KEY": "from-env"}, clear=True):
                    self.assertEqual(keys.get("gemini"), "from-env")


if __name__ == "__main__":
    unittest.main()
