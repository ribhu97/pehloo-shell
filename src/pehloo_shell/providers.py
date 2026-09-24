"""Inference backends `pls` can talk to, and model discovery against them.

Every backend here speaks the OpenAI chat-completions API, so the transport in
`cli.py` stays a single urllib call. This module only carries what the rest of
the CLI needs per backend: where the API lives, which model to fall back on, and
where the API key comes from.

`url` is always the *base* URL (`.../v1`); `.chat_url` and `.models_url` derive
the two endpoints from it. Stored config keeps the full chat-completions URL,
which is what earlier versions wrote, and `chat_url()` accepts both spellings so
hand-written config files keep working.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass


@dataclass(frozen=True)
class Provider:
    """One OpenAI-compatible backend."""

    name: str  # canonical id, stored in shell-config.json
    label: str  # human wording for the setup wizard
    url: str  # base URL, no /chat/completions suffix
    default_model: str
    key_env: str  # environment variable holding the API key ("" if not needed)
    key_url: str  # where a user can create a key ("" if not needed)
    api_key_required: bool

    @property
    def chat_url(self) -> str:
        return chat_url(self.url)

    @property
    def models_url(self) -> str:
        return models_url(self.url)


LOCAL_PROVIDER = Provider(
    name="llama.cpp",
    label="llama.cpp, Ollama, LM Studio or vLLM",
    url="http://127.0.0.1:8080/v1",
    default_model="LFM2.5-1.2B-Instruct-Q8_0.gguf",
    key_env="",
    key_url="",
    api_key_required=False,
)

HOSTED_PROVIDERS = (
    Provider(
        name="cerebras",
        label="Cerebras — very fast hosted models, free tier",
        url="https://api.cerebras.ai/v1",
        default_model="gpt-oss-120b",
        key_env="CEREBRAS_API_KEY",
        key_url="https://cloud.cerebras.ai",
        api_key_required=True,
    ),
    Provider(
        name="groq",
        label="Groq — very fast hosted models, free tier",
        url="https://api.groq.com/openai/v1",
        default_model="llama-3.3-70b-versatile",
        key_env="GROQ_API_KEY",
        key_url="https://console.groq.com/keys",
        api_key_required=True,
    ),
    Provider(
        name="openrouter",
        label="OpenRouter — many models behind one key",
        url="https://openrouter.ai/api/v1",
        default_model="openai/gpt-4o-mini",
        key_env="OPENROUTER_API_KEY",
        key_url="https://openrouter.ai/keys",
        api_key_required=True,
    ),
)

PROVIDERS: dict[str, Provider] = {p.name: p for p in (LOCAL_PROVIDER, *HOSTED_PROVIDERS)}

# Spellings users (and the earlier Cerebras-only version) may already have in a
# config file or environment variable.
ALIASES = {
    "llama.cpp": "llama.cpp",
    "llamacpp": "llama.cpp",
    "llama_cpp": "llama.cpp",
    "local": "llama.cpp",
    "cerebras.ai": "cerebras",
    "openrouter.ai": "openrouter",
}


def provider_for(name: str) -> Provider:
    """Look up a provider, or raise a RuntimeError naming the supported ones.

    Silently falling back to the local default on a typo would send requests to
    the wrong server, so an unknown name stops the CLI instead.
    """
    key = name.strip().lower()
    if not key:
        return LOCAL_PROVIDER
    canonical = ALIASES.get(key, key)
    if canonical in PROVIDERS:
        return PROVIDERS[canonical]
    supported = ", ".join(PROVIDERS)
    raise RuntimeError(f"unknown provider {name!r} (supported: {supported}; or pass --url for any OpenAI-compatible server)")


def chat_url(url: str) -> str:
    """The chat-completions endpoint for `url`, accepting a base or a full URL."""
    base = url.strip().rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    return base + "/chat/completions"


def models_url(url: str) -> str:
    """The `/models` endpoint that pairs with a chat-completions URL."""
    base = url.strip().rstrip("/")
    return base.removesuffix("/chat/completions") + "/models"


def list_models(url: str, api_key: str = "", timeout: float = 5.0) -> list[str]:
    """Ask the server which models it serves, in the order it reports them.

    Raises RuntimeError with a readable message: the setup wizard prints it and
    offers a retry, which is how a user notices a server that is not running yet.
    """
    endpoint = models_url(url)
    headers = {"User-Agent": "pehloo-shell/0.1"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(endpoint, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")[:200]
        raise RuntimeError(f"{endpoint} returned HTTP {error.code}: {detail}") from error
    except urllib.error.URLError as error:
        raise RuntimeError(f"could not reach {endpoint}: {error.reason}") from error
    except (TimeoutError, json.JSONDecodeError) as error:
        raise RuntimeError(f"invalid or timed-out response from {endpoint}: {error}") from error

    entries = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(entries, list):
        raise RuntimeError(f"unexpected response from {endpoint}: expected a JSON object with a 'data' list")

    models: list[str] = []
    for entry in entries:
        model_id = entry.get("id") if isinstance(entry, dict) else None
        if model_id and str(model_id) not in models:
            models.append(str(model_id))
    return models
