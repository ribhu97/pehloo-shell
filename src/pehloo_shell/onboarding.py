"""First-run setup: pick a backend, find its models, write shell-config.json.

`pls` calls `run_wizard()` when there is no config file yet, so a new user gets a
working backend instead of a connection error. The wizard is plain question/answer
flow over stdin — no terminal-cursor tricks — so it stays readable and testable.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from pehloo_shell.providers import (
    HOSTED_PROVIDERS,
    LOCAL_PROVIDER,
    Provider,
    chat_url,
    list_models,
)

# Terminal branding, matching pehloo.xyz: boxed status tags and ▸ progress lines.
BANNER = """\
╔══════════════════════════════╗
║   PLS_SETUP: MODEL_BACKEND   ║
╚══════════════════════════════╝
▸ pehloo-shell · a Pehloo tool (pehloo.xyz)"""


def ask(question: str, default: str = "") -> str:
    """Prompt for one line, returning `default` when the user presses Enter."""
    suffix = f" [{default}]" if default else ""
    answer = input(f"{question}{suffix}: ").strip()
    return answer or default


def ask_yes_no(question: str, default: bool = True) -> bool:
    """Ask a yes/no question; anything unrecognised asks again rather than guessing."""
    hint = "Y/n" if default else "y/N"
    while True:
        answer = input(f"{question} [{hint}]: ").strip().lower()
        if not answer:
            return default
        if answer in {"y", "yes"}:
            return True
        if answer in {"n", "no"}:
            return False
        print("  please answer y or n")


def choose_model(models: list[str], default: str) -> str:
    """Let the user pick a detected model by number, or type one that is not listed."""
    # A provider's default model is often not installed on a local server, so the
    # first detected model becomes the default instead of an unusable name.
    fallback = default if default in models else (models[0] if models else default)
    for index, model in enumerate(models, start=1):
        marker = "  (default)" if model == fallback else ""
        print(f"  {index}. {model}{marker}")
    while True:
        answer = ask("Model number or name", fallback)
        if answer.isdigit() and 1 <= int(answer) <= len(models):
            return models[int(answer) - 1]
        if answer:
            return answer
        print("  a model is required")


def discover_models(url: str, api_key: str) -> list[str]:
    """List the server's models, retrying when it is unreachable.

    Returns an empty list when the user gives up, so the caller can fall back to
    a typed-in model name instead of losing the whole setup.
    """
    while True:
        try:
            models = list_models(url, api_key)
        except RuntimeError as error:
            print(f"  ! {error}")
            models = []
        if models:
            return models
        if not ask_yes_no("Try the model list again?", default=False):
            return []


def configure_local() -> dict[str, str]:
    """Collect settings for a self-hosted OpenAI-compatible server."""
    print(f"\nLocal server: {LOCAL_PROVIDER.label} — any OpenAI-compatible server.")
    url = ask("Server URL", LOCAL_PROVIDER.url)
    api_key = ask("API key (leave blank if the server has none)", "")
    models = discover_models(url, api_key)
    if not models:
        print("  starting without a model list; type the model name your server serves")
    model = choose_model(models, LOCAL_PROVIDER.default_model)
    return _config(provider=LOCAL_PROVIDER, url=url, model=model, api_key=api_key)


def configure_hosted() -> dict[str, str]:
    """Collect settings for one of the hosted OpenAI-compatible providers."""
    print("\nHosted providers:")
    for index, provider in enumerate(HOSTED_PROVIDERS, start=1):
        print(f"  {index}. {provider.label}")

    while True:
        answer = ask("Provider number", "1")
        if answer.isdigit() and 1 <= int(answer) <= len(HOSTED_PROVIDERS):
            provider = HOSTED_PROVIDERS[int(answer) - 1]
            break
        print("  please pick one of the numbers above")

    from_env = os.environ.get(provider.key_env, "") if provider.key_env else ""
    if from_env:
        print(f"  found {provider.key_env} in your environment")
    else:
        print(f"  create a key at {provider.key_url}")

    api_key = ask(f"{provider.key_env or 'API key'} (stored in your config file)", from_env)
    # A key that already lives in the environment is not copied into the config
    # file; the CLI reads the environment variable first anyway.
    stored_key = "" if api_key == from_env else api_key

    models = discover_models(provider.url, api_key)
    if not models:
        print(f"  starting without a model list; the default is {provider.default_model}")
    model = choose_model(models, provider.default_model)
    return _config(provider=provider, url=provider.url, model=model, api_key=stored_key)


def _config(provider: Provider, url: str, model: str, api_key: str) -> dict[str, str]:
    """Assemble the config file body, omitting an empty API key."""
    config = {
        "inference_provider": provider.name,
        "url": chat_url(url),
        "model_slug": model,
    }
    if api_key:
        config["api_key"] = api_key
    return config


def write_config(config: dict[str, str], path: Path) -> Path:
    """Write shell-config.json readable only by the user — it may hold an API key."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    os.chmod(path, 0o600)
    return path


def run_wizard(path: Path) -> dict[str, str]:
    """Run the whole setup flow and save the result to `path`."""
    print(BANNER)
    print(f"▸ your answers are saved to {path} (re-run any time with `pls --setup`)")
    if ask_yes_no("\nUse a local model server?", default=True):
        config = configure_local()
    else:
        config = configure_hosted()
    write_config(config, path)
    print(f"▸ saved {path}")
    print(f"▸ provider={config['inference_provider']}  url={config['url']}  model={config['model_slug']}")
    return config
