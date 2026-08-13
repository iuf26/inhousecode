#!/usr/bin/env bash
#
# Copilot CLI `agentStop` handler - the post-generation trigger.
#
# When the agent finishes a turn, this hook scans what it just wrote. If the
# scan finds problems, the hook returns {"decision":"block", "reason": ...} and
# the *same* agent, with its full context still loaded, is handed the findings
# and made to fix them. No second model is spawned and no diff has to be
# re-explained, which is why this is far cheaper than reviewing at commit time.
#
# Safety rails:
#   - never blocks more than agentStop.maxTurns times per session
#   - fails open: any internal error exits 0 so a broken hook cannot trap a session
#   - reports only; the agent does the fixing

set -uo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
INHOUSECODE_HOME="$(cd -- "$SCRIPT_DIR/.." && pwd)"
export INHOUSECODE_HOME

# Fail open: emit nothing and let the turn end normally.
give_up() { exit 0; }
trap give_up ERR

# shellcheck source=../lib/common.sh
source "$INHOUSECODE_HOME/lib/common.sh" 2>/dev/null || give_up

PAYLOAD="$(cat 2>/dev/null)" || give_up
[ -n "$PAYLOAD" ] || give_up

resolve_python || give_up

read_payload_field() {
  printf '%s' "$PAYLOAD" | "${PYTHON_CMD[@]}" -c '
import json, sys
try:
    payload = json.load(sys.stdin)
except (ValueError, TypeError):
    raise SystemExit(0)
key = sys.argv[1]
value = payload.get(key)
if value is None:
    # Accept both the camelCase and the VS Code compatible payload shapes.
    alias = {"sessionId": "session_id", "cwd": "cwd"}.get(key)
    value = payload.get(alias) if alias else None
print("" if value is None else value)
' "$1" 2>/dev/null
}

SESSION_ID="$(read_payload_field sessionId)"
WORK_DIR="$(read_payload_field cwd)"
[ -n "$WORK_DIR" ] && [ -d "$WORK_DIR" ] || give_up
cd "$WORK_DIR" || give_up

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || give_up
cd "$REPO_ROOT" || give_up
export REPO_ROOT

load_config >/dev/null 2>&1 || give_up
[ "${INHOUSECODE_AGENT_STOP_STATIC:-0}" = "1" ] ||
  [ "${INHOUSECODE_AGENT_STOP_AI:-0}" = "1" ] || give_up

# --- per-session block budget ------------------------------------------------
STATE_DIR="$REPO_ROOT/.inhousecode/cache/agent-stop"
mkdir -p "$STATE_DIR" 2>/dev/null || give_up
SAFE_SESSION="$(printf '%s' "${SESSION_ID:-unknown}" | tr -c 'A-Za-z0-9._-' '_')"
COUNTER_FILE="$STATE_DIR/$SAFE_SESSION.count"
BLOCKS_SO_FAR="$(cat "$COUNTER_FILE" 2>/dev/null || echo 0)"
case "$BLOCKS_SO_FAR" in ''|*[!0-9]*) BLOCKS_SO_FAR=0 ;; esac
[ "$BLOCKS_SO_FAR" -ge "$INHOUSECODE_AGENT_STOP_MAX_TURNS" ] && give_up

# --- scan what the agent just wrote ------------------------------------------
INHOUSECODE_CACHE_ROOT="$REPO_ROOT/.inhousecode/cache/agent-stop-$$"
export INHOUSECODE_CACHE_ROOT
mkdir -p "$INHOUSECODE_CACHE_ROOT" 2>/dev/null || give_up
cleanup() { rm -rf -- "$INHOUSECODE_CACHE_ROOT"; }
trap cleanup EXIT

CHANGED="$INHOUSECODE_CACHE_ROOT/changed.txt"
{
  git diff --name-only --diff-filter=ACMR
  git diff --cached --name-only --diff-filter=ACMR
  git ls-files --others --exclude-standard
} 2>/dev/null | sort -u > "$CHANGED"
[ -s "$CHANGED" ] || give_up

ENVELOPE="$INHOUSECODE_CACHE_ROOT/scan.json"
WORK_ORDER=""

if [ "${INHOUSECODE_AGENT_STOP_STATIC:-0}" = "1" ]; then
  INHOUSECODE_TARGET_MODE="worktree" \
  INHOUSECODE_SEMGREP_CONFIGS="$INHOUSECODE_STATIC_SEMGREP_CONFIGS" \
    bash "$INHOUSECODE_HOME/lib/static_scan.sh" > "$ENVELOPE" 2>/dev/null || give_up

  # static_report.py exits non-zero *by design* when it finds blocking issues.
  # Without the `|| true` the ERR trap reads that as an internal fault and fails
  # open - which would silently skip the exact case this hook exists for.
  REPORT="$(strip_cr "$("${PYTHON_CMD[@]}" "$INHOUSECODE_HOME/lib/static_report.py" "$ENVELOPE" 2>/dev/null)")" || true
  validate_gate_output "$REPORT" "$STATIC_FINDING_MARKER" "$STATIC_VERDICT_PREFIX" || give_up

  SELECTION="${INHOUSECODE_STATIC_FIX_SEVERITY:-all}"
  WORK_ORDER="$(findings_as_work_order "$REPORT" "$STATIC_FINDING_MARKER" "$SELECTION" "semgrep")"
fi

# The AI pass is opt-in (agentStop.ai) because it costs a full model call on
# every turn end. When enabled, only blocking findings are handed back - a stop
# hook that argued about naming after every turn would be unusable.
if [ "${INHOUSECODE_AGENT_STOP_AI:-0}" = "1" ]; then
  # shellcheck source=../lib/copilot.sh
  source "$INHOUSECODE_HOME/lib/copilot.sh" 2>/dev/null || give_up
  # shellcheck source=../lib/gate_ai.sh
  source "$INHOUSECODE_HOME/lib/gate_ai.sh" 2>/dev/null || give_up

  if ensure_copilot >/dev/null 2>&1; then
    cp "$CHANGED" "$INHOUSECODE_CACHE_ROOT/scan-files.txt" 2>/dev/null || give_up
    TARGET_MODE="path" TARGET_PATH="the files changed in this turn" ai_build_prompt
    run_review_agent "$AI_PROMPT" "$INHOUSECODE_CACHE_ROOT/ai-review.log"
    if [ "$REVIEW_RC" -eq 0 ] &&
       validate_gate_output "$REVIEW_OUTPUT" "$AI_FINDING_MARKER" "$AI_VERDICT_PREFIX"; then
      AI_WORK_ORDER="$(findings_as_work_order \
        "$REVIEW_OUTPUT" "$AI_FINDING_MARKER" "blocking" "code review")"
      [ -n "$AI_WORK_ORDER" ] &&
        WORK_ORDER="${WORK_ORDER:+$WORK_ORDER

}$AI_WORK_ORDER"
    fi
  fi
fi

[ -n "$WORK_ORDER" ] || give_up

printf '%s' "$((BLOCKS_SO_FAR + 1))" > "$COUNTER_FILE"

REASON="inhousecode reviewed the code from this turn and found issues.

Fix them now, like a senior engineer: read the affected code, fix the underlying
cause rather than silencing the check, and do not suppress a finding unless it is
genuinely a false positive - in which case say so and explain why.

$WORK_ORDER

Attempt $((BLOCKS_SO_FAR + 1)) of $INHOUSECODE_AGENT_STOP_MAX_TURNS."

# One JSON object on stdout, encoded by Python so the reason is always escaped.
REASON="$REASON" "${PYTHON_CMD[@]}" -c '
import json, os
print(json.dumps({"decision": "block", "reason": os.environ["REASON"]}))
'
exit 0
