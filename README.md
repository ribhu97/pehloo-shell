```
██████╗ ███████╗██╗  ██╗██╗      ██████╗  ██████╗
██╔══██╗██╔════╝██║  ██║██║     ██╔═══██╗██╔═══██╗
██████╔╝█████╗  ███████║██║     ██║   ██║██║   ██║
██╔═══╝ ██╔══╝  ██╔══██║██║     ██║   ██║██║   ██║
██║     ███████╗██║  ██║███████╗╚██████╔╝╚██████╔╝
╚═╝     ╚══════╝╚═╝  ╚═╝╚══════╝ ╚═════╝  ╚═════╝
```

# pls

**Natural language in, shell command out. Review it, then press `y`.**

`pls` is the Pehloo shell assistant — from [Pehloo](https://pehloo.xyz), AI
tools for builders who ship. It asks an OpenAI-compatible model to turn your
request into one shell command, shows it to you, and waits:

```console
$ pls "list the 10 largest directories in the current folder"
du -h --max-depth=1 | sort -hr | head -n 10
[y] run  [n] reject  [c] change >
```

- `y` runs the command in your shell; `pls` exits with its status.
- `n` or Enter rejects it — nothing runs.
- `c` asks the model to change it (e.g. type `sort by size instead`) and shows
  the revision, with the previous command as context.

## Install

```bash
curl -fsSL https://<your-host>/install.sh | sh    # once install.sh is hosted
sh install.sh                                     # from a checkout
```

The installer works at user level — no sudo, no system Python — using uv, pipx
or pip, whichever you have, and prints the installed `pls` path plus the
`export PATH=…` line if you need one. It installs the `pehloo-shell` package
from PyPI; point it elsewhere with `--source` / `$PEHLOO_SHELL_SOURCE`:

```bash
sh install.sh --source "git+https://github.com/your-org/pehloo-shell"
```

Already have a Python tool runner? Skip the script:

```bash
uv tool install pehloo-shell     # or: pipx install pehloo-shell
```

For development see [AGENTS.md](AGENTS.md) (`uv sync`, then `.venv/bin/pls`).
Note that `pipx install .` and `uv tool install .` copy the code — rerun them
after changing the CLI.

## Setup

The first run with no config asks which backend to use:

```console
╔══════════════════════════════╗
║   PLS_SETUP: MODEL_BACKEND   ║
╚══════════════════════════════╝
▸ pehloo-shell · a Pehloo tool (pehloo.xyz)
▸ your answers are saved to ~/.pehloo/shell-config.json (re-run any time with `pls --setup`)

Use a local model server? [Y/n]: y

Local server: llama.cpp, Ollama, LM Studio or vLLM — any OpenAI-compatible server.
Server URL [http://127.0.0.1:8080/v1]:
API key (leave blank if the server has none):
  1. LFM2.5-1.2B-Instruct-Q8_0.gguf  (default)
  2. MiniCPM5-2B
Model number or name [1]:
```

- **Local** (`y`): any OpenAI-compatible server — llama.cpp, Ollama, LM Studio,
  vLLM. `pls` reads its `/v1/models` list so you can pick a model instead of
  guessing a name.
- **Hosted** (`n`): Cerebras, Groq or OpenRouter. The wizard tells you where to
  create a key and detects the provider's models with it. A key already in your
  environment is used without being copied into the config file.

Re-run setup any time with `pls --setup`, or edit `~/.pehloo/shell-config.json`
by hand.

## Non-interactive

```bash
echo "show files changed today" | pls    # prints the command, runs nothing
pls --markdown "show my current directory"
```

When stdin is not a terminal — pipes, scripts, CI — `pls` prints the command and
stops. Nothing executes without an explicit `y` at a terminal.

## Environment variables

Handy for CI, or to keep the API key out of the config file. They override the
config file; command-line flags override both.

| Variable | Meaning |
| --- | --- |
| `PEHLOO_SHELL_CONFIG` | where the config file lives (default `~/.pehloo/shell-config.json`) |
| `PEHLOO_SHELL_PROVIDER` | `llama.cpp`, `cerebras`, `groq` or `openrouter` |
| `PEHLOO_SHELL_API_KEY` | API key for any provider |
| `CEREBRAS_API_KEY`, `GROQ_API_KEY`, `OPENROUTER_API_KEY` | provider-specific keys |
| `LFM_SHELL_URL` | chat-completions URL of any OpenAI-compatible server |
| `LFM_SHELL_MODEL` | model name to send |

Read the command before you press `y`: model output can be destructive.
