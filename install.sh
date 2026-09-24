#!/bin/sh
# Install the `pls` CLI from pehloo-shell.
#
#   curl -fsSL https://example.com/install.sh | sh
#
# Options:
#   --source SPEC   what to install (default: the `pehloo-shell` package)
#                   examples: --source .
#                             --source "git+https://github.com/you/pehloo-shell"
#
# Installs into your user account only: no sudo, no system Python, no files
# outside your home directory. Run it again to upgrade.
set -eu

SOURCE="${PEHLOO_SHELL_SOURCE:-pehloo-shell}"
# Fallback used when the PyPI package is not available (see the install step).
REPO_SOURCE="git+https://github.com/ribhu97/pehloo-shell"
MIN_PYTHON="3.10"

usage() {
    cat <<'EOF'
Install the pls CLI.

Usage: install.sh [--source SPEC]

  --source SPEC   pip requirement to install (default: the pehloo-shell package
                  on PyPI, falling back to the GitHub repository when the
                  package is not published). Also read from $PEHLOO_SHELL_SOURCE.
  --help          show this message.

Installing from a checkout of this repository installs that checkout.
EOF
}

while [ $# -gt 0 ]; do
    case "$1" in
        --source|-s)
            [ $# -ge 2 ] || { echo "install.sh: --source needs a value" >&2; exit 2; }
            SOURCE="$2"
            shift 2
            ;;
        --help|-h)
            usage
            exit 0
            ;;
        *)
            echo "install.sh: unknown option '$1'" >&2
            usage >&2
            exit 2
            ;;
    esac
done

# --- Banner -----------------------------------------------------------------

cat <<'BANNER'

██████╗ ███████╗██╗  ██╗██╗      ██████╗  ██████╗
██╔══██╗██╔════╝██║  ██║██║     ██╔═══██╗██╔═══██╗
██████╔╝█████╗  ███████║██║     ██║   ██║██║   ██║
██╔═══╝ ██╔══╝  ██╔══██║██║     ██║   ██║██║   ██║
██║     ███████╗██║  ██║███████╗╚██████╔╝╚██████╔╝
╚═╝     ╚══════╝╚═╝  ╚═╝╚══════╝ ╚═════╝  ╚═════╝
[ PLS_INSTALL ]  pehloo-shell · a Pehloo tool (pehloo.xyz)

BANNER

# Running inside the repository? Install that, so `sh install.sh` in a checkout
# does the obvious thing.
if [ "$SOURCE" = "pehloo-shell" ] && [ -f pyproject.toml ] && [ -f src/pehloo_shell/cli.py ]; then
    SOURCE="."
    echo "▸ installing from this checkout"
fi

# --- Python -----------------------------------------------------------------

PY=""
for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1; then
        PY="$(command -v "$candidate")"
        break
    fi
done

if [ -z "$PY" ]; then
    echo "install.sh: python3 not found." >&2
    echo "  macOS:  brew install python" >&2
    echo "  Debian: sudo apt install python3 python3-pip" >&2
    exit 1
fi

if ! "$PY" -c "import sys; raise SystemExit(0 if sys.version_info >= tuple(int(p) for p in '$MIN_PYTHON'.split('.')) else 1)"; then
    echo "install.sh: python $MIN_PYTHON or newer is required, found $("$PY" -V 2>&1)." >&2
    exit 1
fi

# --- Install ----------------------------------------------------------------

installer=""

# Install one pip requirement with whichever tool this machine has.
try_install() {
    spec="$1"
    if [ -z "$installer" ]; then
        if command -v uv >/dev/null 2>&1; then
            installer="uv"
        elif command -v pipx >/dev/null 2>&1; then
            installer="pipx"
        else
            installer="pip"
        fi
    fi
    case "$installer" in
        uv)   echo "▸ uv tool install $spec"; uv tool install --force "$spec" ;;
        pipx) echo "▸ pipx install $spec"; pipx install --force "$spec" ;;
        *)    echo "▸ $PY -m pip install --user --upgrade $spec"; "$PY" -m pip install --user --upgrade "$spec" ;;
    esac
}

if ! try_install "$SOURCE"; then
    if [ "$SOURCE" = "pehloo-shell" ]; then
        # Nothing published on PyPI yet (or PyPI is down): install straight from
        # the repository so the advertised `curl … | sh` always works.
        echo "▸ pehloo-shell is not on PyPI yet — installing from $REPO_SOURCE"
        if ! try_install "$REPO_SOURCE"; then
            echo "install.sh: could not install $REPO_SOURCE." >&2
            exit 1
        fi
    else
        echo "install.sh: could not install $SOURCE." >&2
        if [ "$installer" = "pip" ]; then
            echo "  This is often an externally-managed environment (PEP 668). Install uv or pipx and rerun:" >&2
            echo "    curl -LsSf https://astral.sh/uv/install.sh | sh" >&2
        fi
        exit 1
    fi
fi

# --- Report -----------------------------------------------------------------

case "$installer" in
    uv)   bin_dir="${UV_TOOL_BIN_DIR:-$HOME/.local/bin}" ;;
    pipx) bin_dir="${PIPX_BIN_DIR:-$HOME/.local/bin}" ;;
    *)    bin_dir="$("$PY" -c 'import sysconfig; print(sysconfig.get_path("scripts", scheme="posix_user"))')" ;;
esac
installed="$bin_dir/pls"

if [ ! -x "$installed" ]; then
    echo "install.sh: $installer finished but $installed is missing." >&2
    echo "  Look for the tool in $bin_dir and report this at the project's issue tracker." >&2
    exit 1
fi
echo "▸ installed: $installed"

if ! command -v pls >/dev/null 2>&1; then
    echo "▸ $bin_dir is not on your PATH. Add it:"
    echo "    export PATH=\"$bin_dir:\$PATH\""
elif [ "$(command -v pls)" != "$installed" ]; then
    # A different pls earlier on PATH would silently win over this install.
    echo "▸ note: the 'pls' on your PATH is $(command -v pls), not this one."
fi

case "$installer" in
    uv)   echo "▸ upgrade:   uv tool upgrade pehloo-shell" ;;
    pipx) echo "▸ upgrade:   pipx upgrade pehloo-shell" ;;
    *)    echo "▸ upgrade:   $PY -m pip install --user --upgrade pehloo-shell" ;;
esac

# --- Setup ------------------------------------------------------------------

# `curl … | sh` is non-interactive and `pls --setup` needs a terminal to ask its
# questions. In that one case, hand off so a new user lands straight in the
# wizard. An existing config means setup already happened: just upgrade.
setup_path="${PEHLOO_SHELL_CONFIG:-$HOME/.pehloo/shell-config.json}"

# The signature of `curl … | sh`: stdin is the script (a pipe) while stdout is
# the user's terminal. That is the only case where we can hand off — and the
# wizard must read from the terminal device (`/dev/tty`), because the pipe on
# stdin is the script, not a user. Skipped when a config already exists, when
# the script itself runs on a terminal, or with no controlling terminal (CI).
if [ ! -f "$setup_path" ] && [ ! -t 0 ] && [ -t 1 ] && [ -c /dev/tty ]; then
    if [ -x "$installed" ]; then
        echo
        echo "▸ setup: launching 'pls --setup' — first launch picks your model backend"
        echo
        # Run the binary directly, not through `$SHELL -c`: stdout is already this
        # terminal, and a login shell would only re-read PATH from rc files the
        # wizard does not need.
        "$installed" --setup < /dev/tty \
            || echo "▸ setup skipped; run 'pls --setup' any time" >&2
        exit 0
    fi
fi

cat <<'EOF'

▸ next:    pls "list files by size"   — the first run sets up your model backend
▸ local:   llama.cpp, Ollama, LM Studio or vLLM (any OpenAI-compatible server)
▸ hosted:  Cerebras · Groq · OpenRouter
▸ config:  ~/.pehloo/shell-config.json · re-run setup with `pls --setup`
EOF
