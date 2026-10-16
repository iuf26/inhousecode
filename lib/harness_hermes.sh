#!/usr/bin/env bash
#
# Harness adapter: Hermes (Nous Research / Claude Code compatible).
#
# Hermes has its own chat command. This adapter looks for 'hermes' first, then
# falls back to 'claude'.
#
# See lib/harness.sh for the interface each adapter must provide.

# --- binary resolution -------------------------------------------------------

harness_resolve_bin() {
  # Explicit override wins.
  if [ -n "${HERMES_BIN:-}" ] && [ -x "${HERMES_BIN}" ]; then
    printf '%s\n' "${HERMES_BIN}"
    return 0
  fi
  local candidate
  for candidate in hermes claude; do
    if command -v "$candidate" >/dev/null 2>&1; then
      printf '%s\n' "$(command -v "$candidate")"
      return 0
    fi
  done
  return 1
}

# --- agent commands ----------------------------------------------------------
# Identical to claude-code: same CLI, same flags. Only the binary differs.

harness_review_cmd() {
  local prompt="$1" log="$2" timeout="$3" model="$4" verbose="$5"
  local model_flag=()
  [ -n "$model" ] && model_flag=(-m "$model")
  local verbose_flag=()
  [ "$verbose" = "1" ] && verbose_flag=(-v)
  local write_root="${INHOUSECODE_CACHE_ROOT:-${TMPDIR:-/tmp}}"

  HERMES_WRITE_SAFE_ROOT="$write_root" "$TIMEOUT_BIN" "$timeout" "$HARNESS_BIN" chat \
    -q "$prompt" --oneshot --quiet --ignore-rules --toolsets file \
    --max-turns 15 "${model_flag[@]+"${model_flag[@]}"}" \
    "${verbose_flag[@]+"${verbose_flag[@]}"}" > "$log" 2>&1 < /dev/null
  HARNESS_RC=$?
}

harness_fix_cmd() {
  local prompt="$1" log="$2" budget="$3" model="$4" verbose="$5"
  local model_flag=()
  [ -n "$model" ] && model_flag=(-m "$model")
  local verbose_flag=()
  [ "$verbose" = "1" ] && verbose_flag=(-v)

  "$TIMEOUT_BIN" "$budget" "$HARNESS_BIN" chat -q "$prompt" --oneshot --quiet \
    --ignore-rules --toolsets file,terminal --yolo --max-turns 20 \
    "${model_flag[@]+"${model_flag[@]}"}" \
    "${verbose_flag[@]+"${verbose_flag[@]}"}" > "$log" 2>&1 < /dev/null
  HARNESS_RC=$?
}

# harness_discover_cmd <prompt> <log> <budget> <model> <verbose>
# Read + Bash only, no Edit/Write tool at all -- see harness_claude_code.sh
# for why `inhousecode discover` needs this narrower shape.
harness_discover_cmd() {
  local prompt="$1" log="$2" budget="$3" model="$4" verbose="$5"
  local model_flag=()
  [ -n "$model" ] && model_flag=(-m "$model")
  local verbose_flag=()
  [ "$verbose" = "1" ] && verbose_flag=(-v)

  "$TIMEOUT_BIN" "$budget" "$HARNESS_BIN" chat -q "$prompt" --oneshot --quiet \
    --ignore-rules --toolsets file,terminal --yolo --max-turns 20 \
    "${model_flag[@]+"${model_flag[@]}"}" \
    "${verbose_flag[@]+"${verbose_flag[@]}"}" > "$log" 2>&1 < /dev/null
  HARNESS_RC=$?
}

harness_explain_cmd() {
  local prompt="$1" model="$2"
  local model_flag=()
  [ -n "$model" ] && model_flag=(-m "$model")

  "$HARNESS_BIN" chat -q "$prompt" --toolsets file --ignore-rules \
    "${model_flag[@]+"${model_flag[@]}"}" < /dev/tty > /dev/tty 2>&1
  HARNESS_RC=$?
}
