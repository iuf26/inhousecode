#!/usr/bin/env bash
#
# Harness abstraction layer.
#
# Loads the right adapter based on INHOUSECODE_HARNESS and exposes a uniform
# interface for the rest of the codebase: resolve, ensure, and the agent
# commands. The adapter files live beside this one as harness_<name>.sh.
#
# Every adapter must define:
#   harness_resolve_bin                locate the CLI binary -> prints the path
#   harness_review_cmd  <5 args>       run a read-only headless review
#   harness_fix_cmd     <5 args>       run a write-enabled headless fix
#   harness_explain_cmd <2 args>       run an interactive explain session
#
# Each command function sets HARNESS_RC on return.

# --- named constants ---------------------------------------------------------
SUPPORTED_HARNESSES="copilot claude-code codex hermes"

# --- state -------------------------------------------------------------------
# Set by ensure_harness; used by adapter command functions.
HARNESS_BIN=""
HARNESS_RC=0

# --- adapter loading ---------------------------------------------------------

_harness_loaded=""

load_harness() {
  local harness="${INHOUSECODE_HARNESS:-copilot}"
  [ "$harness" = "$_harness_loaded" ] && return 0
  local adapter="$INHOUSECODE_HOME/lib/harness_${harness//-/_}.sh"
  if [ ! -f "$adapter" ]; then
    fail "inhousecode: unknown harness '$harness' (no adapter at $adapter)"
    return 1
  fi
  # shellcheck disable=SC1090
  source "$adapter" || {
    fail "inhousecode: could not load harness adapter: $adapter"
    return 1
  }
  _harness_loaded="$harness"
}

# --- public interface --------------------------------------------------------

# resolve_harness_bin -- find the CLI binary for the configured harness.
# Prints the path. Returns non-zero if the binary cannot be found.
resolve_harness_bin() {
  load_harness || return 1
  harness_resolve_bin
}

# ensure_harness -- verify that the harness CLI and timeout are available.
# Sets HARNESS_BIN. Replaces the old ensure_copilot.
ensure_harness() {
  load_harness || return 1
  HARNESS_BIN="$(harness_resolve_bin)" || {
    local name="${INHOUSECODE_HARNESS:-copilot}"
    fail "inhousecode: $name CLI was not found. Run 'inhousecode doctor' for help."
    return 1
  }
  resolve_timeout || {
    fail "inhousecode: GNU timeout (or gtimeout) is required to bound agent runs."
    return 1
  }
}
