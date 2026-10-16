#!/usr/bin/env bash
#
# Harness adapter: OpenAI Codex CLI.
# See lib/harness.sh for the interface each adapter must provide.

harness_resolve_bin() {
  if [ -n "${CODEX_BIN:-}" ] && [ -x "${CODEX_BIN}" ]; then
    printf '%s\n' "$CODEX_BIN"
    return 0
  fi
  command -v codex 2>/dev/null
}

_codex_runner() {
  local budget="$1"
  CODEX_RUNNER=()
  [ -n "${TIMEOUT_BIN:-}" ] && CODEX_RUNNER=("$TIMEOUT_BIN" "$budget")
}

# Read-only, ephemeral, and isolated from repository/user instructions. Codex's
# OS sandbox is the write boundary; the prompt is not trusted as one.
harness_review_cmd() {
  local prompt="$1" log="$2" timeout="$3" model="$4" verbose="$5"
  del_unused="$verbose"
  local model_flag=()
  [ -n "$model" ] && model_flag=(-m "$model")
  _codex_runner "$timeout"

  printf '%s' "$prompt" | "${CODEX_RUNNER[@]+"${CODEX_RUNNER[@]}"}" "$HARNESS_BIN" exec \
    -C "$REPO_ROOT" --sandbox read-only --ephemeral --ignore-user-config \
    --ignore-rules --json --color never "${model_flag[@]+"${model_flag[@]}"}" - \
    > "$log" 2>&1
  HARNESS_RC=$?
}

# Repairs need workspace writes but remain ephemeral and non-interactive.
harness_fix_cmd() {
  local prompt="$1" log="$2" budget="$3" model="$4" verbose="$5"
  del_unused="$verbose"
  local model_flag=()
  [ -n "$model" ] && model_flag=(-m "$model")
  _codex_runner "$budget"

  printf '%s' "$prompt" | "${CODEX_RUNNER[@]+"${CODEX_RUNNER[@]}"}" "$HARNESS_BIN" exec \
    -C "$REPO_ROOT" --sandbox workspace-write --ephemeral --ignore-user-config \
    --ignore-rules -c 'approval_policy="never"' --json --color never \
    "${model_flag[@]+"${model_flag[@]}"}" - > "$log" 2>&1
  HARNESS_RC=$?
}

# Discovery may inspect and invoke the governed candidate CLI, but Codex never
# receives workspace write permission from this path.
harness_discover_cmd() {
  local prompt="$1" log="$2" budget="$3" model="$4" verbose="$5"
  del_unused="$verbose"
  local model_flag=()
  [ -n "$model" ] && model_flag=(-m "$model")
  _codex_runner "$budget"

  printf '%s' "$prompt" | "${CODEX_RUNNER[@]+"${CODEX_RUNNER[@]}"}" "$HARNESS_BIN" exec \
    -C "$REPO_ROOT" --sandbox read-only --ephemeral --ignore-user-config \
    --ignore-rules -c 'approval_policy="never"' --json --color never \
    "${model_flag[@]+"${model_flag[@]}"}" - > "$log" 2>&1
  HARNESS_RC=$?
}

harness_explain_cmd() {
  local prompt="$1" model="$2"
  local model_flag=()
  [ -n "$model" ] && model_flag=(-m "$model")

  "$HARNESS_BIN" -C "$REPO_ROOT" --sandbox read-only \
    "${model_flag[@]+"${model_flag[@]}"}" "$prompt" \
    < /dev/tty > /dev/tty 2>&1
  HARNESS_RC=$?
}
