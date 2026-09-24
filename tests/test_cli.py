import io
import json
import os
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from pehloo_shell.cli import (
    choose_action,
    clean_request,
    clean_response,
    generate_command,
    load_config,
    main,
    resolve_settings,
)


class CliTests(unittest.TestCase):
    """Shared helper: a config file, so `main` does not start the setup wizard."""

    def write_config_file(self, directory: str, config: dict[str, str] | None = None) -> str:
        path = os.path.join(directory, "shell-config.json")
        with open(path, "w", encoding="utf-8") as config_file:
            json.dump(
                config
                or {
                    "inference_provider": "llama.cpp",
                    "url": "http://127.0.0.1:8080/v1/chat/completions",
                    "model_slug": "m",
                },
                config_file,
            )
        return path

    def test_clean_request_accepts_slashes_and_hashes(self):
        self.assertEqual(clean_request("// list the ten largest folders"), "list the ten largest folders")
        self.assertEqual(clean_request("  # show hidden files"), "show hidden files")

    def test_clean_response_removes_markdown_fence(self):
        self.assertEqual(clean_response("```bash\ndu -h | sort -hr\n```"), "du -h | sort -hr")
        self.assertEqual(clean_response("pwd"), "pwd")

    def test_generate_command_sends_openai_compatible_request(self):
        response = io.BytesIO(json.dumps({"choices": [{"message": {"content": "pwd"}}]}).encode())
        with patch("urllib.request.urlopen") as open_url:
            open_url.return_value.__enter__.return_value = response
            command = generate_command("current directory", "http://localhost/v1/chat/completions", "lfm", 2)
            request = open_url.call_args.args[0]
        payload = json.loads(request.data)
        self.assertEqual(command, "pwd")
        self.assertEqual(request.headers["User-agent"], "pehloo-shell/0.1")
        self.assertEqual(payload["model"], "lfm")
        self.assertEqual(payload["messages"][-1]["content"], "current directory")

    def test_load_config_reads_shell_config_json(self):
        with tempfile.TemporaryDirectory() as config_dir:
            config_path = os.path.join(config_dir, "shell-config.json")
            with open(config_path, "w", encoding="utf-8") as config_file:
                json.dump(
                    {
                        "inference_provider": "cerebras",
                        "url": "https://api.cerebras.ai/v1/chat/completions",
                        "model_slug": "gpt-oss-120b",
                        "api_key": "json-key",
                    },
                    config_file,
                )

            with patch.dict(os.environ, {"PEHLOO_SHELL_CONFIG": config_path, "CEREBRAS_API_KEY": ""}, clear=False):
                provider, url, model, api_key = resolve_settings(load_config())

        self.assertEqual(provider, "cerebras")
        self.assertEqual(url, "https://api.cerebras.ai/v1/chat/completions")
        self.assertEqual(model, "gpt-oss-120b")
        self.assertEqual(api_key, "json-key")

    def test_generate_command_adds_cerebras_authorization_header(self):
        response = io.BytesIO(json.dumps({"choices": [{"message": {"content": "pwd"}}]}).encode())
        with patch("urllib.request.urlopen") as open_url:
            open_url.return_value.__enter__.return_value = response
            generate_command(
                "current directory",
                "https://api.cerebras.ai/v1/chat/completions",
                "gpt-oss-120b",
                2,
                "cerebras",
                "test-key",
            )
            request = open_url.call_args.args[0]

        self.assertEqual(request.headers["Authorization"], "Bearer test-key")

    def test_env_api_key_overrides_config_key(self):
        with patch.dict(os.environ, {"CEREBRAS_API_KEY": "env-key"}, clear=False):
            provider, url, model, api_key = resolve_settings({"inference_provider": "cerebras", "api_key": "json-key"})

        self.assertEqual(provider, "cerebras")
        self.assertEqual(url, "https://api.cerebras.ai/v1/chat/completions")
        self.assertEqual(model, "gpt-oss-120b")
        self.assertEqual(api_key, "env-key")

    def test_unknown_provider_stops_instead_of_silently_going_local(self):
        errors = io.StringIO()
        with tempfile.TemporaryDirectory() as config_dir:
            missing_config = os.path.join(config_dir, "missing-shell-config.json")
            environment = {"PEHLOO_SHELL_CONFIG": missing_config, "PEHLOO_SHELL_PROVIDER": "not-a-provider"}
            with patch.dict(os.environ, environment, clear=False):
                with patch("pehloo_shell.cli.stdin_is_interactive", return_value=False):
                    with redirect_stderr(errors):
                        self.assertEqual(main(["echo something"]), 1)
        self.assertIn("unknown provider", errors.getvalue())

    def test_action_choices(self):
        self.assertEqual(choose_action("Y"), "run")
        self.assertEqual(choose_action("c"), "revise")
        self.assertEqual(choose_action("n"), "reject")
        self.assertEqual(choose_action(""), "reject")
        self.assertEqual(choose_action("what?"), "ask")

    def test_non_interactive_runs_print_the_command_and_never_execute_it(self):
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as config_dir:
            config_path = self.write_config_file(config_dir)
            with patch.dict(os.environ, {"PEHLOO_SHELL_CONFIG": config_path}, clear=False):
                with patch("pehloo_shell.cli.stdin_is_interactive", return_value=False):
                    with patch("pehloo_shell.cli.generate_command", return_value="echo safe"):
                        with patch("pehloo_shell.cli.subprocess.run") as run:
                            with redirect_stdout(output):
                                self.assertEqual(main(["echo something"]), 0)

        self.assertEqual(output.getvalue(), "echo safe\n")
        run.assert_not_called()

    def test_main_uses_config_without_command_flags(self):
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as config_dir:
            config_path = os.path.join(config_dir, "shell-config.json")
            with open(config_path, "w", encoding="utf-8") as config_file:
                json.dump(
                    {
                        "inference_provider": "cerebras",
                        "url": "https://example.test/v1/chat/completions",
                        "model_slug": "fast",
                    },
                    config_file,
                )

            with patch.dict(os.environ, {"PEHLOO_SHELL_CONFIG": config_path, "CEREBRAS_API_KEY": ""}, clear=False):
                with patch("pehloo_shell.cli.stdin_is_interactive", return_value=False):
                    with patch("pehloo_shell.cli.generate_command", return_value="echo safe") as generate:
                        with redirect_stdout(output):
                            self.assertEqual(main(["echo something"]), 0)

        self.assertEqual(generate.call_args.args[1], "https://example.test/v1/chat/completions")
        self.assertEqual(generate.call_args.args[2], "fast")
        self.assertEqual(generate.call_args.args[4], "cerebras")
        self.assertEqual(generate.call_args.args[5], "")
        self.assertEqual(output.getvalue(), "echo safe\n")

    def test_confirmation_runs_the_command_and_passes_its_exit_status_through(self):
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as config_dir:
            config_path = self.write_config_file(config_dir)
            with patch.dict(os.environ, {"PEHLOO_SHELL_CONFIG": config_path}, clear=False):
                with patch("pehloo_shell.cli.stdin_is_interactive", return_value=True):
                    with patch("pehloo_shell.cli.generate_command", return_value="echo safe"):
                        with patch("builtins.input", side_effect=["y"]):
                            with patch("pehloo_shell.cli.subprocess.run") as run:
                                run.return_value = subprocess.CompletedProcess(args="echo safe", returncode=7)
                                with redirect_stdout(output):
                                    self.assertEqual(main(["echo something"]), 7)

        self.assertEqual(run.call_args.args, ("echo safe",))
        self.assertTrue(run.call_args.kwargs["shell"])
        self.assertEqual(output.getvalue(), "echo safe\n")

    def test_empty_reply_rejects_the_command(self):
        with tempfile.TemporaryDirectory() as config_dir:
            config_path = self.write_config_file(config_dir)
            with patch.dict(os.environ, {"PEHLOO_SHELL_CONFIG": config_path}, clear=False):
                with patch("pehloo_shell.cli.stdin_is_interactive", return_value=True):
                    with patch("pehloo_shell.cli.generate_command", return_value="rm -rf /"):
                        with patch("builtins.input", side_effect=[""]):
                            with patch("pehloo_shell.cli.subprocess.run") as run:
                                with redirect_stdout(io.StringIO()):
                                    self.assertEqual(main(["delete everything"]), 0)

        run.assert_not_called()

    def test_change_revises_with_the_previous_command_as_context(self):
        with tempfile.TemporaryDirectory() as config_dir:
            config_path = self.write_config_file(config_dir)
            with patch.dict(os.environ, {"PEHLOO_SHELL_CONFIG": config_path}, clear=False):
                with patch("pehloo_shell.cli.stdin_is_interactive", return_value=True):
                    with patch(
                        "pehloo_shell.cli.generate_command", side_effect=["echo safe", "echo safe | sort"]
                    ) as generate:
                        with patch("builtins.input", side_effect=["c", "sort by size", "y"]):
                            with patch("pehloo_shell.cli.subprocess.run") as run:
                                run.return_value = subprocess.CompletedProcess(args="", returncode=0)
                                with redirect_stdout(io.StringIO()):
                                    self.assertEqual(main(["echo something"]), 0)

        self.assertEqual(generate.call_args_list[0].args[0], "echo something")
        self.assertEqual(generate.call_args_list[1].kwargs, {"previous_command": "echo safe", "change": "sort by size"})
        self.assertEqual(run.call_args.args, ("echo safe | sort",))

    def test_setup_flag_runs_the_wizard_without_asking_for_a_request(self):
        with tempfile.TemporaryDirectory() as config_dir:
            config_path = os.path.join(config_dir, "shell-config.json")
            with patch.dict(os.environ, {"PEHLOO_SHELL_CONFIG": config_path}, clear=False):
                with patch("pehloo_shell.cli.stdin_is_interactive", return_value=True):
                    with patch("pehloo_shell.cli.run_wizard", return_value={"inference_provider": "llama.cpp"}) as wizard:
                        with patch("builtins.input", side_effect=AssertionError("must not prompt for a request")):
                            with redirect_stdout(io.StringIO()):
                                self.assertEqual(main(["--setup"]), 0)

        self.assertEqual(wizard.call_args.args[0], Path(config_path))


if __name__ == "__main__":
    unittest.main()
