#!/usr/bin/env bash
#
# Harness adapter: Anthropic Claude Code CLI.
#
# Implements the harness contract for the Claude Code CLI (claude).
# See lib/harness.sh for the interface each adapter must provide.

# --- binary resolution -------------------------------------------------------

harness_resolve_bin() {
  # Explicit override wins.
  if [ -n "${CLAUDE_CODE_BIN:-}" ] && [ -x "${CLAUDE_CODE_BIN}" ]; then
    printf '%s\n' "${CLAUDE_CODE_BIN}"
    return 0
  fi
  local candidate
  for candidate in claude; do
    if command -v "$candidate" >/dev/null 2>&1; then
      printf '%s\n' "$(command -v "$candidate")"
      return 0
    fi
  done
  return 1
}

# --- agent commands ----------------------------------------------------------

# harness_review_cmd <prompt> <log> <timeout> <model> <verbose>
# Read-only headless review. Writes output to <log>.
# Sets HARNESS_RC on return.
harness_review_cmd() {
  local prompt="$1" log="$2" timeout="$3" model="$4" verbose="$5"
  local model_flag=()
  [ -n "$model" ] && model_flag=(--model "$model")
  local fmt=()
  [ -n "${PYTHON_CMD:-}" ] && fmt=(--output-format json)
  local verbose_flag=()
  [ "$verbose" = "1" ] && verbose_flag=(--verbose)

  "$TIMEOUT_BIN" "$timeout" "$HARNESS_BIN" -p "$prompt" \
    "${model_flag[@]+"${model_flag[@]}"}" \
    "${verbose_flag[@]+"${verbose_flag[@]}"}" \
    --allowedTools 'Read' \
    --disallowedTools 'Edit,Write,Bash,WebSearch,WebFetch' \
    --permission-mode bypassPermissions \
    --max-turns 15 \
    "${fmt[@]+"${fmt[@]}"}" > "$log" 2>&1 < /dev/null
  HARNESS_RC=$?
}

# harness_fix_cmd <prompt> <log> <budget> <model> <verbose>
# Write-enabled headless fix. Writes output to <log>.
# Sets HARNESS_RC on return.
harness_fix_cmd() {
  local prompt="$1" log="$2" budget="$3" model="$4" verbose="$5"
  local model_flag=()
  [ -n "$model" ] && model_flag=(--model "$model")
  local fmt=()
  [ -n "${PYTHON_CMD:-}" ] && fmt=(--output-format json)
  local verbose_flag=()
  [ "$verbose" = "1" ] && verbose_flag=(--verbose)

  "$TIMEOUT_BIN" "$budget" "$HARNESS_BIN" -p "$prompt" \
    "${model_flag[@]+"${model_flag[@]}"}" \
    "${verbose_flag[@]+"${verbose_flag[@]}"}" \
    --allowedTools 'Read,Edit,Write,Bash' \
    --disallowedTools 'WebSearch,WebFetch' \
    --permission-mode bypassPermissions \
    --max-turns 20 \
    "${fmt[@]+"${fmt[@]}"}" > "$log" 2>&1 < /dev/null
  HARNESS_RC=$?
}

# harness_discover_cmd <prompt> <log> <budget> <model> <verbose>
# Read + Bash only, no Edit/Write tool. Discovery may call the governed
# `inhousecode memory candidate add` interface; it cannot edit repository files
# or call OpenViking directly.
harness_discover_cmd() {
  local prompt="$1" log="$2" budget="$3" model="$4" verbose="$5"
  local model_flag=()
  [ -n "$model" ] && model_flag=(--model "$model")
  local fmt=()
  [ -n "${PYTHON_CMD:-}" ] && fmt=(--output-format json)
  local verbose_flag=()
  [ "$verbose" = "1" ] && verbose_flag=(--verbose)

  "$TIMEOUT_BIN" "$budget" "$HARNESS_BIN" -p "$prompt" \
    "${model_flag[@]+"${model_flag[@]}"}" \
    "${verbose_flag[@]+"${verbose_flag[@]}"}" \
    --allowedTools 'Read,Bash' \
    --disallowedTools 'Edit,Write,WebSearch,WebFetch' \
    --permission-mode bypassPermissions \
    --max-turns 20 \
    "${fmt[@]+"${fmt[@]}"}" > "$log" 2>&1 < /dev/null
  HARNESS_RC=$?
}

# harness_explain_cmd <prompt> <model>
# Interactive session on the developer's terminal.
# Sets HARNESS_RC on return.
harness_explain_cmd() {
  local prompt="$1" model="$2"
  local model_flag=()
  [ -n "$model" ] && model_flag=(--model "$model")

  "$HARNESS_BIN" "$prompt" "${model_flag[@]+"${model_flag[@]}"}" \
    --allowedTools 'Read' < /dev/tty > /dev/tty 2>&1
  HARNESS_RC=$?
}
