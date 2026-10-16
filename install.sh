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
#                    [--with-timeout|--no-timeout]
#                    [--harness copilot|claude-code|codex|hermes]
#                    [--adversarial-model <model>|--no-adversarial]
#                    [--fix-by-default|--no-fix-by-default]
#                    [-y|--yes] [--non-interactive]

set -uo pipefail

DEFAULT_BIN_DIR="$HOME/.local/bin"
INHOUSECODE_HOME="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

BIN_DIR="$DEFAULT_BIN_DIR"
SEMGREP_MODE=""   # "" = ask, "yes" = install, "no" = skip
TIMEOUT_MODE=""   # same tri-state, for the brew coreutils offer
HARNESS=""        # "" = ask, or one of: copilot, claude-code, codex, hermes
ADVERSARIAL_MODE=""   # "" = ask, "no" = disabled, or "yes" (model set separately)
ADVERSARIAL_MODEL=""  # a model id on the chosen harness, or "" for default
FIX_BY_DEFAULT_MODE="" # "" = preserve unless interactive, "yes" = enabled, "no" = disabled
ASSUME_YES=0
NON_INTERACTIVE=0

while [ "$#" -gt 0 ]; do
  case "$1" in
    --bin-dir) shift; BIN_DIR="${1:?--bin-dir needs a value}" ;;
    --with-semgrep) SEMGREP_MODE="yes" ;;
    --no-semgrep) SEMGREP_MODE="no" ;;
    --with-timeout) TIMEOUT_MODE="yes" ;;
    --no-timeout) TIMEOUT_MODE="no" ;;
    --harness)
      shift
      case "${1:-}" in
        copilot|claude-code|codex|hermes) HARNESS="$1" ;;
        *) echo "install: --harness must be copilot, claude-code, codex, or hermes" >&2; exit 2 ;;
      esac
      ;;
    --adversarial-model) shift; ADVERSARIAL_MODE="yes"; ADVERSARIAL_MODEL="${1:?--adversarial-model needs a value}" ;;
    --no-adversarial) ADVERSARIAL_MODE="no" ;;
    --fix-by-default) FIX_BY_DEFAULT_MODE="yes" ;;
    --no-fix-by-default) FIX_BY_DEFAULT_MODE="no" ;;
    # Legacy flags — still accepted, mapped to --harness copilot
    --with-copilot) HARNESS="copilot" ;;
    --no-copilot) HARNESS="" ;;
    -y|--yes) ASSUME_YES=1 ;;
    --non-interactive) NON_INTERACTIVE=1 ;;
    -h|--help)
      sed -n '2,17p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
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

# pick <prompt> <option1> <option2> ... -> prints the chosen option
pick() {
  local prompt="$1"; shift
  local options=("$@") i reply
  if [ "$INTERACTIVE" != "1" ]; then
    printf '%s' "${options[0]}"
    return 0
  fi
  printf '\n  %s\n' "$prompt" > /dev/tty
  for i in "${!options[@]}"; do
    printf '    [%d] %s\n' "$((i + 1))" "${options[$i]}" > /dev/tty
  done
  printf '  > ' > /dev/tty
  IFS= read -r reply < /dev/tty || reply=""
  case "$reply" in
    ''|*[!0-9]*) reply=0 ;;
    *) reply=$((reply - 1)) ;;
  esac
  if [ "$reply" -ge 0 ] && [ "$reply" -lt "${#options[@]}" ]; then
    printf '%s' "${options[$reply]}"
  else
    printf '%s' "${options[0]}"
  fi
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

# --- AI harness selection -----------------------------------------------------
#
# This is the Hermes-style experience: the user picks which AI CLI they want to
# use as the backend for review, repair, and explain. The choice is written into
# the default config so every `inhousecode` invocation uses it without a flag.

HARNESS_DESCRIPTIONS=(
  "hermes       — Hermes + OpenViking memory  (recommended)"
  "copilot      — GitHub Copilot CLI  (copilot)"
  "claude-code  — Anthropic Claude Code CLI  (claude)"
  "codex        — OpenAI Codex CLI  (codex)"
)
if [ -z "$HARNESS" ] && [ "$INTERACTIVE" = "1" ]; then
  say ""
  say "  Which AI CLI do you want inhousecode to use as its backend?"
  say "  (This runs the AI code review, repairs, and explain sessions.)"
  say ""
  for i in "${!HARNESS_DESCRIPTIONS[@]}"; do
    printf '    [%d] %s\n' "$((i + 1))" "${HARNESS_DESCRIPTIONS[$i]}"
  done
  printf '\n  Pick a number [1]: ' > /dev/tty
  IFS= read -r harness_reply < /dev/tty || harness_reply=""
  case "$harness_reply" in
    2) HARNESS="copilot" ;;
    3) HARNESS="claude-code" ;;
    4) HARNESS="codex" ;;
    *) HARNESS="hermes" ;;
  esac
elif [ -z "$HARNESS" ]; then
  # Non-interactive default: copilot (backward compatible)
  HARNESS="copilot"
fi

say ""
ok "AI harness: $HARNESS"

# --- harness CLI check --------------------------------------------------------

check_harness_binary() {
  case "$HARNESS" in
    copilot)
      if [ -n "${COPILOT_BIN:-}" ] && [ -x "$COPILOT_BIN" ]; then
        ok "Copilot CLI ($COPILOT_BIN)"
        return 0
      fi
      if command -v copilot >/dev/null 2>&1; then
        ok "Copilot CLI ($(command -v copilot))"
        return 0
      fi
      miss "Copilot CLI not found - the AI gate needs it (https://github.com/github/copilot-cli)"
      offer_install_copilot
      ;;
    claude-code)
      if [ -n "${CLAUDE_CODE_BIN:-}" ] && [ -x "$CLAUDE_CODE_BIN" ]; then
        ok "Claude Code CLI ($CLAUDE_CODE_BIN)"
        return 0
      fi
      if command -v claude >/dev/null 2>&1; then
        ok "Claude Code CLI ($(command -v claude))"
        return 0
      fi
      miss "Claude Code CLI not found - install it: npm install -g @anthropic-ai/claude-code"
      offer_install_claude_code
      ;;
    hermes)
      if [ -n "${HERMES_BIN:-}" ] && [ -x "$HERMES_BIN" ]; then
        ok "Hermes CLI ($HERMES_BIN)"
        return 0
      fi
      if command -v hermes >/dev/null 2>&1; then
        ok "Hermes CLI ($(command -v hermes))"
        return 0
      fi
      if command -v claude >/dev/null 2>&1; then
        ok "Hermes: falling back to Claude Code CLI ($(command -v claude))"
        return 0
      fi
      miss "Hermes CLI not found - install it: pip install hermes-ai, or install Claude Code: npm install -g @anthropic-ai/claude-code"
      ;;
    codex)
      if [ -n "${CODEX_BIN:-}" ] && [ -x "$CODEX_BIN" ]; then
        ok "Codex CLI ($CODEX_BIN)"
        return 0
      fi
      if command -v codex >/dev/null 2>&1; then
        ok "Codex CLI ($(command -v codex))"
        return 0
      fi
      miss "Codex CLI not found - install it: npm install -g @openai/codex"
      ;;
  esac
}

offer_install_copilot() {
  local copilot_cmd=""
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
  [ -z "$copilot_cmd" ] && return 0
  if ask "Install Copilot CLI now with '$copilot_cmd'?"; then
    say "  Installing Copilot CLI..."
    eval "$copilot_cmd"
    command -v copilot >/dev/null 2>&1 &&
      ok "Copilot CLI installed" ||
      miss "Copilot CLI install did not put 'copilot' on PATH - you may need a new shell"
  fi
}

offer_install_claude_code() {
  local claude_cmd=""
  if command -v npm >/dev/null 2>&1; then
    claude_cmd="npm install -g @anthropic-ai/claude-code"
  fi
  [ -z "$claude_cmd" ] && return 0
  if ask "Install Claude Code CLI now with '$claude_cmd'?"; then
    say "  Installing Claude Code CLI..."
    eval "$claude_cmd"
    command -v claude >/dev/null 2>&1 &&
      ok "Claude Code CLI installed" ||
      miss "Claude Code CLI install did not put 'claude' on PATH - you may need a new shell"
  fi
}

check_harness_binary

# --- adversarial review model -------------------------------------------------
#
# Adversarial review is the heavy, opt-in second mode: several critical lenses
# each review a whole PR on a DIFFERENT model than the primary review, on the
# same harness you just chose. Picking that model here turns the mode on; it is
# still invoked deliberately per run with `inhousecode review --adversarial`.

if [ -z "$ADVERSARIAL_MODE" ] && [ "$INTERACTIVE" = "1" ]; then
  say ""
  say "  Adversarial review (optional): the deep, final review for a whole PR."
  say "  Instead of one reviewer, several independent critics each attack the"
  say "  change from a different angle (correctness, design, simplicity) on a"
  say "  DIFFERENT model than your normal review, then a lead pass merges them"
  say "  into one verdict. Run it before merging, not on every commit."
  say "  You can set that model now, or skip and configure it later."
  if ask "Enable adversarial review and set its model now?"; then
    printf '  Model id for adversarial lenses (blank = same as primary review): ' > /dev/tty
    IFS= read -r ADVERSARIAL_MODEL < /dev/tty || ADVERSARIAL_MODEL=""
    ADVERSARIAL_MODE="yes"
  else
    ADVERSARIAL_MODE="no"
  fi
fi
[ -z "$ADVERSARIAL_MODE" ] && ADVERSARIAL_MODE="no"

if [ "$ADVERSARIAL_MODE" = "yes" ]; then
  if [ -n "$ADVERSARIAL_MODEL" ]; then
    ok "Adversarial review: enabled (model: $ADVERSARIAL_MODEL)"
  else
    ok "Adversarial review: enabled (lenses use the primary review model)"
  fi
else
  ok "Adversarial review: disabled (enable later in config)"
fi

# --- default repair policy ----------------------------------------------------

if [ -z "$FIX_BY_DEFAULT_MODE" ] && [ "$INTERACTIVE" = "1" ]; then
  say ""
  say "  Automatic repair is optional. When enabled, every review repairs all"
  say "  static and AI findings, then re-reviews the result. --no-fix still wins."
  if ask "Fix findings by default?"; then
    FIX_BY_DEFAULT_MODE="yes"
  else
    FIX_BY_DEFAULT_MODE="no"
  fi
fi

case "$FIX_BY_DEFAULT_MODE" in
  yes) ok "Fix findings by default: enabled" ;;
  no)  ok "Fix findings by default: disabled" ;;
  *)   ok "Fix findings by default: unchanged" ;;
esac

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

# --- write the harness choice into the default config -------------------------
#
# The installer's pick is recorded in the shipped default so every invocation
# resolves it without a per-repo override. A team can still override it in
# .inhousecode/config.json for a specific repository.

"$PYTHON" -c "
import json, sys
path = sys.argv[1]
harness = sys.argv[2]
adv_enabled = sys.argv[3] == 'yes'
adv_model = sys.argv[4]
fix_by_default = sys.argv[5]
with open(path) as f:
    cfg = json.load(f)
cfg['harness'] = harness
adv = cfg.setdefault('adversarial', {})
adv['enabled'] = adv_enabled
adv['model'] = adv_model
if fix_by_default:
    cfg.setdefault('review', {})['fixByDefault'] = fix_by_default == 'yes'
with open(path, 'w') as f:
    json.dump(cfg, f, indent=2)
    f.write('\n')
" "$INHOUSECODE_HOME/config/review.config.default.json" "$HARNESS" "$ADVERSARIAL_MODE" "$ADVERSARIAL_MODEL" "$FIX_BY_DEFAULT_MODE"

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

AI harness: $HARNESS
  (change later: edit config/review.config.default.json or set "harness"
   in your repo's .inhousecode/config.json)

Next steps, in any repository you want reviewed:

  cd /path/to/your/repo
  inhousecode init            # creates .inhousecode/ configuration
  inhousecode discover        # optional: proposes governed candidate knowledge
  inhousecode install-hooks   # installs the trigger you configured
  inhousecode doctor          # verify everything resolves

Then just work normally. Run 'inhousecode review' any time for an ad-hoc pass.
EOF
