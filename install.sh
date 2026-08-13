#!/usr/bin/env bash
#
# Install inhousecode for the current user.
#
# Creates a launcher on PATH that points back at this checkout, so `git pull`
# here is the whole upgrade story. Nothing is copied and nothing is vendored.
#
# Interactive by default when run from a terminal: it checks each prerequisite
# and asks before installing or changing anything on your system. Every flag
# below exists to skip a question for scripted/CI installs.
#
#   bash install.sh [--bin-dir <dir>] [--with-semgrep|--no-semgrep]
#                    [--with-timeout|--no-timeout] [--with-copilot|--no-copilot]
#                    [-y|--yes] [--non-interactive]

set -uo pipefail

DEFAULT_BIN_DIR="$HOME/.local/bin"
INHOUSECODE_HOME="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

BIN_DIR="$DEFAULT_BIN_DIR"
SEMGREP_MODE=""   # "" = ask, "yes" = install, "no" = skip
TIMEOUT_MODE=""   # same tri-state, for the brew coreutils offer
COPILOT_MODE=""   # same tri-state, for the Copilot CLI offer
ASSUME_YES=0
NON_INTERACTIVE=0

while [ "$#" -gt 0 ]; do
  case "$1" in
    --bin-dir) shift; BIN_DIR="${1:?--bin-dir needs a value}" ;;
    --with-semgrep) SEMGREP_MODE="yes" ;;
    --no-semgrep) SEMGREP_MODE="no" ;;
    --with-timeout) TIMEOUT_MODE="yes" ;;
    --no-timeout) TIMEOUT_MODE="no" ;;
    --with-copilot) COPILOT_MODE="yes" ;;
    --no-copilot) COPILOT_MODE="no" ;;
    -y|--yes) ASSUME_YES=1 ;;
    --non-interactive) NON_INTERACTIVE=1 ;;
    -h|--help)
      sed -n '2,15p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *) echo "install: unknown option '$1'" >&2; exit 2 ;;
  esac
  shift
done

say()  { printf '%s\n' "$*"; }
ok()   { printf '  OK    %s\n' "$*"; }
miss() { printf '  MISS  %s\n' "$*" >&2; }

# Interactive only when nothing told us not to be, and there's a real terminal
# to talk to. A plain `curl | bash` or CI invocation has no /dev/tty attached
# on stdin, so this degrades to the old skip-by-default behavior automatically.
INTERACTIVE=0
if [ "$NON_INTERACTIVE" = "0" ] && [ "$ASSUME_YES" = "0" ] && [ -t 1 ] && [ -r /dev/tty ]; then
  INTERACTIVE=1
fi

# ask <prompt> [default: N] -> 0 (yes) or 1 (no)
ask() {
  local prompt="$1" reply
  if [ "$ASSUME_YES" = "1" ]; then
    return 0
  fi
  if [ "$INTERACTIVE" != "1" ]; then
    return 1
  fi
  printf '  %s [y/N] ' "$prompt" > /dev/tty
  IFS= read -r reply < /dev/tty || reply=""
  case "$reply" in
    [Yy]|[Yy][Ee][Ss]) return 0 ;;
    *) return 1 ;;
  esac
}

say "inhousecode installer"
say "  source: $INHOUSECODE_HOME"
[ "$INTERACTIVE" = "1" ] && say "  mode:   interactive"
say ""
say "Checking prerequisites..."

command -v git >/dev/null 2>&1 && ok "git" || { miss "git is required"; exit 1; }

PYTHON=""
for candidate in python3 python; do
  if command -v "$candidate" >/dev/null 2>&1 &&
      "$candidate" -c 'import sys; raise SystemExit(sys.version_info.major != 3)' 2>/dev/null; then
    PYTHON="$candidate"
    break
  fi
done
[ -n "$PYTHON" ] && ok "python 3 ($PYTHON)" || { miss "python 3 is required"; exit 1; }

# --- semgrep ------------------------------------------------------------------

if command -v semgrep >/dev/null 2>&1; then
  ok "semgrep"
else
  install_semgrep=0
  case "$SEMGREP_MODE" in
    yes) install_semgrep=1 ;;
    no)  install_semgrep=0 ;;
    *)
      if [ "$INTERACTIVE" = "1" ]; then
        say "  Semgrep runs the deterministic static gate (Phase 1). Without it,"
        say "  inhousecode still works but skips straight to the AI review."
      fi
      ask "Install semgrep now with '$PYTHON -m pip install --user semgrep'?" && install_semgrep=1
      ;;
  esac
  if [ "$install_semgrep" = "1" ]; then
    say "  Installing semgrep with pip..."
    if "$PYTHON" -m pip install --user semgrep; then
      ok "semgrep installed"
    else
      miss "semgrep install failed - install it yourself later: pip install semgrep"
    fi
  else
    miss "semgrep not found - the static gate needs it (pip install semgrep, or re-run with --with-semgrep)"
  fi
fi

# --- Copilot CLI ----------------------------------------------------------------

if command -v copilot >/dev/null 2>&1; then
  ok "Copilot CLI"
else
  # Prefer whichever official method is actually usable here: npm needs Node
  # 22+, brew is macOS/Linux only, the install script is the universal fallback.
  copilot_cmd=""
  if command -v npm >/dev/null 2>&1 && command -v node >/dev/null 2>&1; then
    node_major="$(node -v 2>/dev/null | sed -e 's/^v//' -e 's/\..*//')"
    case "$node_major" in
      ''|*[!0-9]*) ;;
      *) [ "$node_major" -ge 22 ] && copilot_cmd="npm install -g @github/copilot" ;;
    esac
  fi
  if [ -z "$copilot_cmd" ] && command -v brew >/dev/null 2>&1; then
    copilot_cmd="brew install --cask copilot-cli"
  fi
  if [ -z "$copilot_cmd" ] && command -v curl >/dev/null 2>&1; then
    copilot_cmd="curl -fsSL https://gh.io/copilot-install | bash"
  fi

  install_copilot=0
  if [ -n "$copilot_cmd" ]; then
    case "$COPILOT_MODE" in
      yes) install_copilot=1 ;;
      no)  install_copilot=0 ;;
      *)
        if [ "$INTERACTIVE" = "1" ]; then
          say "  Copilot CLI runs Phase 2 (the AI review), every automatic repair, and [e] explain."
        fi
        ask "Install Copilot CLI now with '$copilot_cmd'?" && install_copilot=1
        ;;
    esac
  elif [ "$COPILOT_MODE" = "yes" ]; then
    miss "Copilot CLI not found - no supported install method on this system (need npm+node22, brew, or curl)"
  fi

  if [ "$install_copilot" = "1" ]; then
    say "  Installing Copilot CLI..."
    eval "$copilot_cmd"
    if command -v copilot >/dev/null 2>&1; then
      ok "Copilot CLI installed"
    else
      miss "Copilot CLI install did not put 'copilot' on PATH - you may need to open a new shell, then re-run 'inhousecode doctor'"
    fi
  elif [ -n "$copilot_cmd" ]; then
    miss "Copilot CLI not found - the AI gate and all repairs need it (https://github.com/github/copilot-cli)"
  fi
fi

# --- GNU timeout ----------------------------------------------------------------

if command -v timeout >/dev/null 2>&1 || command -v gtimeout >/dev/null 2>&1; then
  ok "timeout"
elif command -v brew >/dev/null 2>&1; then
  install_timeout=0
  case "$TIMEOUT_MODE" in
    yes) install_timeout=1 ;;
    no)  install_timeout=0 ;;
    *)
      if [ "$INTERACTIVE" = "1" ]; then
        say "  GNU timeout bounds every agent run so a stuck model can't hang a commit."
      fi
      ask "Install it now with 'brew install coreutils' (provides gtimeout)?" && install_timeout=1
      ;;
  esac
  if [ "$install_timeout" = "1" ]; then
    say "  Installing coreutils with brew..."
    if brew install coreutils; then
      ok "coreutils installed"
    else
      miss "coreutils install failed - install it yourself later: brew install coreutils"
    fi
  else
    miss "GNU timeout not found - agent runs cannot be bounded without it (brew install coreutils, or re-run with --with-timeout)"
  fi
else
  miss "GNU timeout not found - agent runs cannot be bounded without it"
fi

# --- launcher -------------------------------------------------------------------

chmod +x "$INHOUSECODE_HOME/bin/inhousecode" "$INHOUSECODE_HOME/hooks/agent-stop.sh" \
  "$INHOUSECODE_HOME/lib"/*.sh 2>/dev/null || true

mkdir -p "$BIN_DIR" || { miss "could not create $BIN_DIR"; exit 1; }
LAUNCHER="$BIN_DIR/inhousecode"
cat > "$LAUNCHER" <<EOF || { miss "could not write $LAUNCHER"; exit 1; }
#!/usr/bin/env bash
# Generated by the inhousecode installer. Points at the checkout below, so
# updating that checkout updates the tool.
exec "$INHOUSECODE_HOME/bin/inhousecode" "\$@"
EOF
chmod +x "$LAUNCHER" || { miss "could not make $LAUNCHER executable"; exit 1; }

say ""
say "Installed launcher: $LAUNCHER"

case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *)
    say "NOTE: $BIN_DIR is not on your PATH."
    RC_FILE=""
    case "${SHELL:-}" in
      */zsh)  RC_FILE="$HOME/.zshrc" ;;
      */bash) RC_FILE="$HOME/.bashrc" ;;
    esac
    added=0
    if [ -n "$RC_FILE" ]; then
      if ask "Add 'export PATH=\"$BIN_DIR:\$PATH\"' to $RC_FILE?"; then
        printf '\n# Added by the inhousecode installer\nexport PATH="%s:$PATH"\n' "$BIN_DIR" >> "$RC_FILE"
        say "  Updated $RC_FILE - restart your shell or 'source $RC_FILE'."
        added=1
      fi
    fi
    if [ "$added" = "0" ]; then
      say "  Add it yourself:"
      say "      export PATH=\"$BIN_DIR:\$PATH\""
    fi
    ;;
esac

cat <<EOF

Next steps, in any repository you want reviewed:

  cd /path/to/your/repo
  inhousecode init            # creates .inhousecode/ (config + team rulebook)
  inhousecode install-hooks   # installs the trigger you configured
  inhousecode doctor          # verify everything resolves

Then just work normally. Run 'inhousecode review' any time for an ad-hoc pass.
EOF
