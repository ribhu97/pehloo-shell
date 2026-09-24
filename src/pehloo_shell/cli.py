from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

from dotenv import load_dotenv

from pehloo_shell.onboarding import run_wizard
from pehloo_shell.providers import LOCAL_PROVIDER, PROVIDERS, provider_for

load_dotenv()

CONFIG_PATH = Path.home() / ".pehloo" / "shell-config.json"
SYSTEM_PROMPT = """You translate requests into shell commands.
Return exactly one shell command and nothing else: no explanation, no prompt symbol,
and no Markdown fence. Prefer portable commands unless the request requires a
platform-specific feature. Never invent placeholder paths or values. Words such as
\"here\" and \"current folder\" mean the shell's current working directory."""
EXAMPLE_REQUEST = "List the 10 largest directories in the current folder."
EXAMPLE_ANSWER = "du -h --max-depth=1 | sort -hr | head -n 10"
# Sent as a follow-up turn when the user presses `c` at the confirmation prompt.
REVISION_PROMPT = "Change that command: {change}"
ACTION_PROMPT = "[y] run  [n] reject  [c] change > "
# Exit status for Ctrl-C / Ctrl-D at a prompt (128 + SIGINT, the shell convention).
INTERRUPTED = 130


def clean_request(value: str) -> str:
    """Remove a leading shell-comment marker while preserving the request."""
    return re.sub(r"^\s*(?://|#)\s*", "", value).strip()


def clean_response(value: str) -> str:
    """Tolerate Markdown fences even though the model is asked not to use them."""
    value = value.strip()
    match = re.fullmatch(r"```(?:bash|sh|shell|zsh)?\s*\n?(.*?)\n?```", value, re.DOTALL | re.IGNORECASE)
    return (match.group(1) if match else value).strip()


def config_path() -> Path:
    return Path(os.environ.get("PEHLOO_SHELL_CONFIG", CONFIG_PATH))


def load_config() -> dict[str, str]:
    path = config_path()
    if not path.exists():
        return {}
    try:
        raw_config = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise RuntimeError(f"invalid config file {path}: {error}") from error
    if not isinstance(raw_config, dict):
        raise RuntimeError(f"invalid config file {path}: expected a JSON object")

    config: dict[str, str] = {}
    aliases = {
        "inference_provider": "inference_provider",
        "provider": "inference_provider",
        "url": "url",
        "model_slug": "model_slug",
        "model": "model_slug",
        "api_key": "api_key",
        "apikey": "api_key",
    }
    for key, value in raw_config.items():
        normalized_key = aliases.get(str(key).strip().lower().replace("-", "_").replace(" ", "_"))
        if normalized_key and value:
            config[normalized_key] = str(value)
    return config


def setting_from_env(name: str, fallback: str) -> str:
    return os.environ.get(name) or fallback


def api_key_for(provider, config: dict[str, str]) -> str:
    """Resolve the API key: the provider's own env var, a generic override, then the config file."""
    candidates = [
        os.environ.get(provider.key_env, "") if provider.key_env else "",
        os.environ.get("PEHLOO_SHELL_API_KEY", ""),
        config.get("api_key", ""),
    ]
    for candidate in candidates:
        if candidate:
            return candidate
    return ""


def resolve_settings(config: dict[str, str]) -> tuple[str, str, str, str]:
    provider = provider_for(setting_from_env("PEHLOO_SHELL_PROVIDER", config.get("inference_provider", LOCAL_PROVIDER.name)))
    url = setting_from_env("LFM_SHELL_URL", config.get("url", provider.chat_url))
    model = setting_from_env("LFM_SHELL_MODEL", config.get("model_slug", provider.default_model))
    return provider.name, url, model, api_key_for(provider, config)


def auth_headers(provider: str, api_key: str = "") -> dict[str, str]:
    """Headers for the chat request. The key is only sent when we have one."""
    backend = provider_for(provider)
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "pehloo-shell/0.1",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    elif backend.api_key_required:
        raise RuntimeError(f"{backend.name} needs an API key: export {backend.key_env} or run `pls --setup`")
    return headers


def build_messages(prompt: str, previous_command: str = "", change: str = "") -> list[dict[str, str]]:
    """Build the chat payload, appending the revision turn when the user asked for a change."""
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": EXAMPLE_REQUEST},
        {"role": "assistant", "content": EXAMPLE_ANSWER},
        {"role": "user", "content": prompt},
    ]
    if previous_command:
        messages.append({"role": "assistant", "content": previous_command})
        messages.append({"role": "user", "content": REVISION_PROMPT.format(change=change)})
    return messages


def generate_command(
    prompt: str,
    url: str,
    model: str,
    timeout: float,
    provider: str = "llama.cpp",
    api_key: str = "",
    previous_command: str = "",
    change: str = "",
) -> str:
    """Ask the model for one command; `previous_command` + `change` ask it to revise one."""
    payload = {
        "model": model,
        "messages": build_messages(prompt, previous_command, change),
        "temperature": 0.2,
        "max_tokens": 8192,
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=auth_headers(provider, api_key),
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            result = json.load(response)
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"server returned HTTP {error.code}: {detail}") from error
    except urllib.error.URLError as error:
        raise RuntimeError(f"could not reach {url}: {error.reason}") from error
    except (TimeoutError, json.JSONDecodeError) as error:
        raise RuntimeError(f"invalid or timed-out response from {url}: {error}") from error

    try:
        content = result["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as error:
        raise RuntimeError(f"unexpected server response: {result!r}") from error

    command = clean_response(content)
    if not command:
        raise RuntimeError("the model returned an empty command")
    return command


def stdin_is_interactive() -> bool:
    """True when both ends are a terminal, so asking the user a question is safe."""
    return sys.stdin.isatty() and sys.stdout.isatty()


def print_command(command: str, markdown: bool) -> None:
    """Print the command, optionally fenced so it can be pasted into Markdown."""
    print(f"```bash\n{command}\n```" if markdown else command)


def choose_action(answer: str) -> str:
    """Map a typed reply to `run`, `reject`, `revise` — or `ask` for anything else.

    Enter and `n` reject: a stray newline must never run a command.
    """
    answer = answer.strip().lower()
    if answer in {"y", "yes"}:
        return "run"
    if answer in {"c", "change", "revise"}:
        return "revise"
    if answer in {"n", "no", ""}:
        return "reject"
    return "ask"


def read_line(prompt: str) -> str | None:
    """Read one line, or None when the user interrupts or closes the prompt."""
    try:
        return input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return None


def run_command(command: str) -> int:
    """Run the confirmed command in the user's shell, passing its exit status through."""
    try:
        return subprocess.run(command, shell=True, check=False).returncode
    except KeyboardInterrupt:
        print()
        return INTERRUPTED


def confirm_and_run(prompt: str, command: str, args: argparse.Namespace, api_key: str) -> int:
    """Show the command and act on the user's choice: run it, reject it, or change it.

    `c` sends the requested change back to the model together with the previous
    command, so iterating does not mean retyping the request. Returns the exit
    status `pls` should exit with.
    """
    while True:
        print_command(command, args.markdown)
        answer = read_line(ACTION_PROMPT)
        if answer is None:
            return INTERRUPTED

        action = choose_action(answer)
        if action == "reject":
            return 0
        if action == "ask":
            continue
        if action == "run":
            return run_command(command)

        change = read_line("how should it change? ")
        if change is None:
            return INTERRUPTED
        if not change:
            continue

        try:
            command = generate_command(
                prompt,
                args.url,
                args.model,
                args.timeout,
                args.provider,
                api_key,
                previous_command=command,
                change=change,
            )
        except RuntimeError as error:
            print(f"pls: {error}", file=sys.stderr)
            return 1


def offer_setup(force: bool) -> dict[str, str]:
    """Run the setup wizard, or explain why we cannot.

    Reached when `--setup` was passed, or when there is no config file yet and the
    user can answer questions. Without a terminal we keep the old behaviour — no
    prompts, default settings — so piping a request into `pls` still works.
    """
    if not stdin_is_interactive():
        if force:
            raise RuntimeError("--setup needs an interactive terminal")
        return {}
    try:
        return run_wizard(config_path())
    except (EOFError, KeyboardInterrupt):
        print("\npls: setup skipped, using default settings", file=sys.stderr)
        return {}


def build_parser(
    provider: str = LOCAL_PROVIDER.name,
    url: str = LOCAL_PROVIDER.chat_url,
    model: str = LOCAL_PROVIDER.default_model,
) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pls",
        description=(
            "Generate a shell command with an OpenAI-compatible model API, then choose "
            "whether to run it, reject it, or change it."
        ),
        epilog="pehloo-shell · a Pehloo tool (https://pehloo.xyz)",
    )
    parser.add_argument("request", nargs="*", help='request, for example: "list files by size"')
    parser.add_argument("--provider", default=provider, choices=sorted(PROVIDERS))
    parser.add_argument("--url", default=url)
    parser.add_argument("--model", default=model)
    parser.add_argument("--timeout", type=float, default=30.0, help="request timeout in seconds")
    parser.add_argument("--markdown", action="store_true", help="wrap output in a bash Markdown fence")
    parser.add_argument("--setup", action="store_true", help="run the backend setup wizard again")
    return parser


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    setup_requested = "--setup" in argv

    try:
        config = load_config()
        if setup_requested or (not config and stdin_is_interactive()):
            config = offer_setup(force=setup_requested)
        provider, url, model, api_key = resolve_settings(config)
    except RuntimeError as error:
        print(f"pls: {error}", file=sys.stderr)
        return 1

    args = build_parser(provider, url, model).parse_args(argv)
    if args.setup and not args.request:
        return 0  # `pls --setup` on its own is only the wizard

    raw_request = " ".join(args.request)
    if not raw_request and not sys.stdin.isatty():
        raw_request = sys.stdin.read()
    if not raw_request:
        answer = read_line("// ")
        if answer is None:
            return INTERRUPTED
        raw_request = answer

    prompt = clean_request(raw_request)
    if not prompt:
        print("pls: a request is required", file=sys.stderr)
        return 2

    try:
        command = generate_command(prompt, args.url, args.model, args.timeout, args.provider, api_key)
    except RuntimeError as error:
        print(f"pls: {error}", file=sys.stderr)
        return 1

    if not stdin_is_interactive():
        # Piped or redirected: print the command and stay out of the way.
        print_command(command, args.markdown)
        return 0
    return confirm_and_run(prompt, command, args, api_key)


if __name__ == "__main__":
    raise SystemExit(main())
