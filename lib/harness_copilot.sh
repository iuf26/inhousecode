#!/usr/bin/env bash
#
# Harness adapter: GitHub Copilot CLI.
#
# Implements the harness contract for the Copilot CLI (copilot).
# See lib/harness.sh for the interface each adapter must provide.

# --- binary resolution -------------------------------------------------------

harness_resolve_bin() {
  # Explicit override wins.
  if [ -n "${COPILOT_BIN:-}" ] && [ -x "${COPILOT_BIN}" ]; then
    printf '%s\n' "${COPILOT_BIN}"
    return 0
  fi
  local candidate
  while IFS= read -r candidate; do
    [ -n "$candidate" ] || continue
    # VS Code ships an internal copy that cannot run headless prompts.
    case "$candidate" in
      *globalStorage/github.copilot-chat/*) continue ;;
    esac
    printf '%s\n' "$candidate"
    return 0
  done < <(type -ap copilot 2>/dev/null)

  # WinGet installs on Windows.
  local base="${LOCALAPPDATA:-$HOME/AppData/Local}"
  base="${base//\\//}"
  for candidate in \
    "$base/Microsoft/WinGet/Packages/GitHub.Copilot_Microsoft.Winget.Source_8wekyb3d8bbwe/copilot.exe" \
    "$base/Microsoft/WinGet/Packages/GitHub.Copilot.Prerelease_Microsoft.Winget.Source_8wekyb3d8bbwe/copilot.exe"; do
    [ -x "$candidate" ] && { printf '%s\n' "$candidate"; return 0; }
  done
  return 1
}

# --- agent commands ----------------------------------------------------------

# harness_review_cmd <prompt> <log> <timeout> <model> <verbose>
# Read-only headless review. Writes output to <log>.
# Sets HARNESS_RC on return.
harness_review_cmd() {
  local prompt="$1" log="$2" timeout="$3" model="$4" verbose="$5"
  local quiet=(--silent)
  [ "$verbose" = "1" ] && quiet=()
  local model_flag=()
  [ -n "$model" ] && model_flag=(--model "$model")
  local fmt=()
  [ -n "${PYTHON_CMD:-}" ] && fmt=(--output-format json)

  "$TIMEOUT_BIN" "$timeout" "$HARNESS_BIN" -p "$prompt" \
    "${model_flag[@]+"${model_flag[@]}"}" "${quiet[@]+"${quiet[@]}"}" \
    --allow-tool=read --deny-tool=write,shell,url --no-ask-user \
    --no-custom-instructions \
    "${fmt[@]+"${fmt[@]}"}" --no-color > "$log" 2>&1 < /dev/null
  HARNESS_RC=$?
}

# harness_fix_cmd <prompt> <log> <budget> <model> <verbose>
# Write-enabled headless fix. Writes output to <log>.
# Sets HARNESS_RC on return.
harness_fix_cmd() {
  local prompt="$1" log="$2" budget="$3" model="$4" verbose="$5"
  local quiet=(--silent)
  [ "$verbose" = "1" ] && quiet=()
  local model_flag=()
  [ -n "$model" ] && model_flag=(--model "$model")
  local fmt=()
  [ -n "${PYTHON_CMD:-}" ] && fmt=(--output-format json)

  "$TIMEOUT_BIN" "$budget" "$HARNESS_BIN" -p "$prompt" \
    "${model_flag[@]+"${model_flag[@]}"}" "${quiet[@]+"${quiet[@]}"}" \
    --allow-tool=read,write --deny-tool=url --no-ask-user \
    "${fmt[@]+"${fmt[@]}"}" --no-color > "$log" 2>&1 < /dev/null
  HARNESS_RC=$?
}

# harness_discover_cmd <prompt> <log> <budget> <model> <verbose>
# Read + shell only, no file-edit tool. Discovery may call the governed
# `inhousecode memory candidate add` interface; it cannot edit repository files
# or call OpenViking directly.
harness_discover_cmd() {
  local prompt="$1" log="$2" budget="$3" model="$4" verbose="$5"
  local quiet=(--silent)
  [ "$verbose" = "1" ] && quiet=()
  local model_flag=()
  [ -n "$model" ] && model_flag=(--model "$model")
  local fmt=()
  [ -n "${PYTHON_CMD:-}" ] && fmt=(--output-format json)

  "$TIMEOUT_BIN" "$budget" "$HARNESS_BIN" -p "$prompt" \
    "${model_flag[@]+"${model_flag[@]}"}" "${quiet[@]+"${quiet[@]}"}" \
    --allow-tool=read,shell --deny-tool=write,url --no-ask-user \
    "${fmt[@]+"${fmt[@]}"}" --no-color > "$log" 2>&1 < /dev/null
  HARNESS_RC=$?
}

# harness_explain_cmd <prompt> <model>
# Interactive session on the developer's terminal.
# Sets HARNESS_RC on return.
harness_explain_cmd() {
  local prompt="$1" model="$2"
  local model_flag=()
  [ -n "$model" ] && model_flag=(--model "$model")

  "$HARNESS_BIN" -i "$prompt" "${model_flag[@]+"${model_flag[@]}"}" \
    --allow-tool=read --deny-tool=url < /dev/tty > /dev/tty 2>&1
  HARNESS_RC=$?
}
