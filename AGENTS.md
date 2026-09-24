# AGENTS.md

Guidance for humans and AI agents working in this repository.

## Project in one line

`pehloo-shell` (CLI: `pls`) turns a natural-language request into a shell command
via an OpenAI-compatible model server (local llama.cpp by default, or Cerebras,
Groq, OpenRouter). It prints the command, then asks whether to run, reject or
change it — nothing executes without an explicit `y`. From Pehloo
(<https://pehloo.xyz>).

## Layout

- `src/pehloo_shell/cli.py` — the `pls` CLI: settings resolution, the model call,
  and the run/reject/change confirmation loop.
- `src/pehloo_shell/providers.py` — the backend registry (local + hosted), URL
  derivation, and `/models` discovery. Add a backend here and nowhere else.
- `src/pehloo_shell/onboarding.py` — the first-run setup wizard and the config
  file writer. Also reachable with `pls --setup`.
- `install.sh` — the `curl … | sh` installer (uv → pipx → pip, user-level only).
- `tests/test_cli.py`, `tests/test_providers.py`, `tests/test_onboarding.py` —
  unit tests (mock the HTTP layer and `input`).
- `benchmark/` is private and gitignored (kept out of the public repo and the
  PyPI sdist "for now"); its tooling and run instructions live in
  `benchmark/AGENTS.md`. The same applies to `.serena/`, `.claude/` and
  `.mcp.json`.

## Environment

- The project uses a `uv`-managed venv (`.venv`):

  ```bash
  uv venv .venv
  uv sync            # installs the `pls` CLI and its one dependency
  ```

  `uv.lock` is committed; keep it in sync when you touch `pyproject.toml`.
  Benchmark tooling (`inspect-ai`, `openai`, `matplotlib`) is not part of the
  package — install it as a local overlay when you work in `benchmark/`:
  `uv pip install --python .venv/bin/python inspect-ai openai matplotlib`
  (`uv sync` removes the overlay again).

- `.env` holds secrets and local defaults (cline-pass judge, local llama-server).
  Never commit a real API key — `.env` is gitignored; put placeholders in
  `.env.example` instead.

- End users install with `install.sh` (`sh install.sh` from a checkout, or
  `curl -fsSL <url> | sh`): uv → pipx → pip, user-level only, no sudo. It
  installs the `pehloo-shell` package from PyPI unless `--source` /
  `$PEHLOO_SHELL_SOURCE` says otherwise.
- After a piped `curl … | sh` install with no config file, `install.sh` runs
  `"$installed" --setup < /dev/tty` so the wizard opens immediately. The guard is
  `[ ! -t 0 ] && [ -t 1 ] && [ -c /dev/tty ]`: the script's stdin is the pipe
  (the script body) and its stdout is the user's terminal. `< /dev/tty` is
  required — without it the child inherits the *script pipe* as stdin and
  `pls --setup` exits with "needs an interactive terminal". Skipped when a
  config already exists, when `sh install.sh` runs on a terminal (the first
  `pls` run opens the wizard itself), or in CI with no controlling terminal.
  A wizard that exits non-zero prints `setup skipped`, and the installer still
  exits 0: the install already succeeded.

## Branding & voice

Public surfaces match <https://pehloo.xyz>:

- The ANSI-shadow `PEHLOO` wordmark (top of `README.md`, header of
  `install.sh`) — the exact 6 lines are on the site's landing page.
- Status tags look like `[ PLS_INSTALL ]` and `[ COMING_SOON ]` — square
  brackets, words_joined_by_underscores, sometimes boxed with `╔═╗`.
- Progress and pointer lines start with `▸` (the wizard, the installer).
- Terse terminal voice: "Natural language in, shell command out." — no
  marketing, no filler. Fonts on the site are Share Tech Mono / Space Mono /
  VT323; accent colour is brand-amber `#d4a017` on cream `#f5f2eb`.
- `pls` itself prints the command then `[y] run  [n] reject  [c] change >`.

## How `pls` behaves (keep these contracts)

- **Nothing executes without an explicit `y`** at the `[y] run  [n] reject
  [c] change` prompt. Enter and `n` reject; unknown keys ask again.
- **Non-interactive runs never execute**: with stdin/stdout not a terminal,
  `pls` prints the command and stops, so pipes and scripts stay safe.
- `y` propagates the command's exit status as `pls`'s own; Ctrl-C/Ctrl-D at a
  prompt is 130; a missing request is 2.
- `c` sends the revision as a follow-up turn (`previous_command` + `change` in
  `generate_command`), so revisions keep the original request as context.
- The setup wizard runs only when there is no config file and the session is
  interactive, or when `--setup` is passed.
- New backends go in `providers.py`; nothing else should know provider URLs or
  API-key environment variables.

## Releasing (PyPI)

`install.sh` defaults to the `pehloo-shell` package on PyPI, so publishing is what
makes `pipx install pehloo-shell` work for everyone else.

Releases go out from `.github/workflows/publish.yml` using trusted publishing —
no API token is stored in the repo or in GitHub secrets. PyPI's publisher form
("pending publisher" for a project that does not exist yet) must match that file
exactly:

| PyPI field | Value |
| --- | --- |
| PyPI Project Name | `pehloo-shell` |
| Owner | `ribhu97` |
| Repository name | `pehloo-shell` |
| Workflow name | `publish.yml` |
| Environment name | `pypi` — the workflow sets `environment: pypi`; leaving this blank on PyPI means deleting that line too |

Then: bump `version` in `pyproject.toml`, commit, tag `v<version>`, publish a
GitHub release. The workflow builds the artifacts, validates their metadata with
`uv publish --dry-run`, and uploads them with OIDC. `workflow_dispatch` re-runs it
on demand; `--check-url` makes that a no-op for files PyPI already has.

Publishing by hand, with a token, still works:

```bash
uv build                                    # dist/*.whl + dist/*.tar.gz
uv publish --dry-run dist/*                 # validates the metadata, stops at credentials

# optional rehearsal on TestPyPI, then install from there
uv publish --publish-url https://test.pypi.org/legacy/ --token "$TESTPYPI_TOKEN" dist/*
pipx install --index-url https://test.pypi.org/simple/ \
    --pip-args="--extra-index-url https://pypi.org/simple/" pehloo-shell

uv publish --token "$PYPI_TOKEN" dist/*     # the real thing
```

- Credentials for the manual path come from `UV_PUBLISH_TOKEN` / `--token`, or a
  token from <https://pypi.org/manage/account/token/>; never put one in the repo.
- Bump `version` in `pyproject.toml` for every upload — PyPI rejects a version it
  already has, so a fix means a new version, not a re-upload.
- The sdist ships the package, tests and docs only; `.env`, `logs/`,
  `benchmark/`, `.serena/`, `.claude/` and `.mcp.json` are excluded (see
  `[tool.hatch.build.targets.sdist]` in `pyproject.toml`). After touching
  packaging, re-check with `tar tzf dist/*.tar.gz` — the sdist must never contain
  `.env`.
- Published installs are copies: `pipx install pehloo-shell` and
  `uv tool install pehloo-shell` need `--force` (or `pipx upgrade` /
  `uv tool upgrade`) to pick up a release.

## Working agreements

1. **Keep code human readable.**
   - No unnecessary abstractions. Plain functions and simple data flow beat clever
     design patterns.
   - No god-functions. If a function does more than one clearly named thing, split it.
   - Inline comments and docstrings explain *why*, not just *what*. A stranger should
     be able to read the code top-to-bottom without spelunking.

## Before committing

- Unit tests should pass: `uv run python -m unittest discover tests`
- CLI still runs: `uv run pls "list files by size"` (interactive), and
  `echo "list files by size" | uv run pls` must print the command and run nothing.
- Installer still parses and installs: `sh -n install.sh`, then
  `uv tool install --force .` (or `sh install.sh`).
- `.env` must not contain real secrets (only placeholders).
