import io
import json
import unittest
import urllib.error
from unittest.mock import patch

from pehloo_shell.providers import chat_url, list_models, models_url, provider_for


class ProviderTests(unittest.TestCase):
    def test_chat_and_models_urls_accept_a_base_or_a_full_url(self):
        self.assertEqual(chat_url("http://127.0.0.1:8080/v1"), "http://127.0.0.1:8080/v1/chat/completions")
        self.assertEqual(chat_url("http://127.0.0.1:8080/v1/chat/completions"), "http://127.0.0.1:8080/v1/chat/completions")
        self.assertEqual(models_url("http://127.0.0.1:8080/v1/chat/completions"), "http://127.0.0.1:8080/v1/models")
        self.assertEqual(models_url("https://api.groq.com/openai/v1/"), "https://api.groq.com/openai/v1/models")

    def test_provider_names_resolve_and_unknown_ones_are_an_error(self):
        self.assertEqual(provider_for("Cerebras.AI").name, "cerebras")
        self.assertEqual(provider_for("").name, "llama.cpp")
        self.assertEqual(provider_for("openrouter").key_env, "OPENROUTER_API_KEY")
        with self.assertRaises(RuntimeError):
            provider_for("ollama-cloud")

    def test_list_models_returns_the_server_ids_and_sends_the_key(self):
        body = {"data": [{"id": "m-b"}, {"id": "m-a"}, {"id": "m-b"}, {"broken": 1}]}
        response = io.BytesIO(json.dumps(body).encode())
        with patch("urllib.request.urlopen") as open_url:
            open_url.return_value.__enter__.return_value = response
            models = list_models("https://api.groq.com/openai/v1", "k-1")
            request = open_url.call_args.args[0]

        self.assertEqual(models, ["m-b", "m-a"])
        self.assertEqual(request.full_url, "https://api.groq.com/openai/v1/models")
        self.assertEqual(request.headers["Authorization"], "Bearer k-1")

    def test_list_models_reports_an_unreachable_server(self):
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("connection refused")):
            with self.assertRaises(RuntimeError) as caught:
                list_models("http://127.0.0.1:8080/v1")

        self.assertIn("could not reach", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
