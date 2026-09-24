import io
import json
import os
import stat
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from pehloo_shell.onboarding import run_wizard


def run_wizard_quietly(path: Path, answers: list[str], models: list[str] | None = None) -> dict[str, str]:
    """Drive the wizard with scripted answers, keeping its questions out of the test output."""
    with patch("builtins.input", side_effect=answers):
        with patch("pehloo_shell.onboarding.list_models", return_value=models or []) as list_models:
            with redirect_stdout(io.StringIO()):
                config = run_wizard(path)
    return config, list_models


class WizardTests(unittest.TestCase):
    def test_local_setup_picks_a_detected_model_and_writes_the_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pehloo" / "shell-config.json"
            # local server, default URL, no API key, second detected model
            config, _ = run_wizard_quietly(path, ["y", "", "", "2"], ["small.gguf", "big.gguf"])

            self.assertEqual(
                config,
                {
                    "inference_provider": "llama.cpp",
                    "url": "http://127.0.0.1:8080/v1/chat/completions",
                    "model_slug": "big.gguf",
                },
            )
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), config)
            # The file can hold an API key, so it must not be world-readable.
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_hosted_setup_stores_the_provider_key_and_url(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "shell-config.json"
            with patch.dict(os.environ, {"GROQ_API_KEY": ""}, clear=False):
                # hosted, Groq (second entry), key, first detected model
                config, _ = run_wizard_quietly(path, ["n", "2", "gk-1", "1"], ["llama-3.3-70b-versatile"])

        self.assertEqual(config["inference_provider"], "groq")
        self.assertEqual(config["url"], "https://api.groq.com/openai/v1/chat/completions")
        self.assertEqual(config["model_slug"], "llama-3.3-70b-versatile")
        self.assertEqual(config["api_key"], "gk-1")

    def test_a_key_already_in_the_environment_is_not_copied_into_the_config_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "shell-config.json"
            with patch.dict(os.environ, {"GROQ_API_KEY": "gk-env"}, clear=False):
                # Enter accepts the key found in the environment
                config, list_models = run_wizard_quietly(path, ["n", "2", "", "1"], ["m"])

        self.assertNotIn("api_key", config)
        self.assertEqual(list_models.call_args.args[1], "gk-env")


if __name__ == "__main__":
    unittest.main()
