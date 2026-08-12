#!/usr/bin/env bash
#
# Copilot CLI invocation layer.
#
# Three very different call shapes are used, and keeping them apart matters:
#
#   review_agent    read-only, headless, no custom instructions. It judges code
#                   and must never be able to write to the tree it is judging.
#   fix_agent       write-enabled and headless. It repairs findings that were
#                   already produced by a gate. It never stages, commits, or pushes.
#   explain_session interactive and developer-driven. It explains findings and
#                   then does whatever the developer asks.
#
# The headless two are wrapped in a hard timeout so a stalled model can never
# hang a commit. The interactive one is not: bounding a human conversation would
# be absurd.

# --- named constants ---------------------------------------------------------
FIX_AGENT_TIMEOUT_MULTIPLIER=2
# The CLI reports cost only on its JSONL stream, so the headless shapes ask for
# it and reconstruct the answer from the same events. The interactive session is
# left in text mode -- it renders its own exit summary, and a developer reading
# a conversation should not be reading JSON.
#
# JSON is requested only when Python is available to read it back. Asking for a
# format nothing can parse would turn every review into an unavailable gate, and
# a cost report is not worth a gate: reporting is the feature, reviewing is the
# product.
NANO_PER_AI_CREDIT=1000000000

agent_output_format() {
  AGENT_OUTPUT_FORMAT=()
  [ -n "${PYTHON_CMD:-}" ] && AGENT_OUTPUT_FORMAT=(--output-format json)
}

REVIEW_PERMISSIONS=(
  --allow-tool=read
  --deny-tool=write,shell,url
  --no-ask-user
  --no-custom-instructions
)
FIX_PERMISSIONS=(
  --allow-tool=read,write
  --deny-tool=url
  --no-ask-user
)
# Read is pre-approved so exploring a finding is frictionless; everything that
# can change the tree is left to prompt, because the developer is right there
# and this session is theirs, not the gate's.
EXPLAIN_PERMISSIONS=(
  --allow-tool=read
  --deny-tool=url
)

copilot_model_flag() {
  # Empty model means "let the Copilot CLI pick", which respects the user's
  # own /model choice instead of pinning a model the team may not have.
  MODEL_FLAG=()
  [ -n "${INHOUSECODE_AI_MODEL:-}" ] && MODEL_FLAG=(--model "$INHOUSECODE_AI_MODEL")
}

# --- cost accounting ---------------------------------------------------------
#
# A review spends the developer's AI budget, so the run says what it spent. The
# numbers are read from the CLI's own usage events rather than estimated: a cost
# this tool guessed at would be worse than no cost at all, because it would be
# believed.
#
# Accounting never affects a verdict. Every failure here degrades to "not
# reported" and the gate proceeds -- being unable to price a review is not a
# reason to block a commit.
USAGE_TOTAL_NANO=0
USAGE_TOTAL_PREMIUM=0
USAGE_RUNS=0
USAGE_BREAKDOWN=""
USAGE_INCOMPLETE=0

usage_reset() {
  USAGE_TOTAL_NANO=0
  USAGE_TOTAL_PREMIUM=0
  USAGE_RUNS=0
  USAGE_BREAKDOWN=""
  USAGE_INCOMPLETE=0
}

# agent_text <log> -- the assistant's answer, as text mode would have printed it.
# Falls back to the raw log when the run was not in JSON mode, so the two
# formats stay interchangeable from the caller's point of view.
agent_text() {
  local log="$1"
  if [ -z "${PYTHON_CMD:-}" ]; then
    cat "$log" 2>/dev/null
    return 0
  fi
  "${PYTHON_CMD[@]}" "$INHOUSECODE_HOME/lib/usage.py" --log "$log" --mode text 2>/dev/null
}

# usage_record <label> <log> -- add one agent run to the running total.
usage_record() {
  local label="$1" log="$2" raw nano premium
  USAGE_RUNS=$((USAGE_RUNS + 1))
  if [ -z "${PYTHON_CMD:-}" ]; then
    USAGE_INCOMPLETE=1
    return 0
  fi
  raw="$("${PYTHON_CMD[@]}" "$INHOUSECODE_HOME/lib/usage.py" --log "$log" --mode usage 2>/dev/null)" || raw=""
  nano="${raw%%	*}"
  premium="${raw##*	}"
  case "$nano" in
    ''|*[!0-9]*) USAGE_INCOMPLETE=1; return 0 ;;
  esac
  case "$premium" in
    ''|*[!0-9]*) premium=0 ;;
  esac
  USAGE_TOTAL_NANO=$((USAGE_TOTAL_NANO + nano))
  USAGE_TOTAL_PREMIUM=$((USAGE_TOTAL_PREMIUM + premium))
  USAGE_BREAKDOWN="${USAGE_BREAKDOWN}${label}	${nano}	${premium}
"
}

# Nano-AIU is an integer count, so the division is done in awk rather than in
# the shell, which cannot divide.
usage_credits() {
  awk -v nano="$1" -v per="$NANO_PER_AI_CREDIT" 'BEGIN { printf "%.3f", nano / per }'
}

# What this run cost, printed once, at the end, next to the verdict it paid for.
#
# The breakdown is shown rather than a single number because the run's cost is
# not one decision: a second opinion, a repair round, and a re-review are each
# something the developer can switch off in config, and a lump sum tells them
# which of those to reach for -- none.
print_usage_summary() {
  [ "$USAGE_RUNS" -gt 0 ] || return 0

  say ""
  say "  Cost            : $(usage_credits "$USAGE_TOTAL_NANO") AI credits across $USAGE_RUNS agent run(s)"
  [ "$USAGE_TOTAL_PREMIUM" -gt 0 ] &&
    say "                    $USAGE_TOTAL_PREMIUM premium request(s)"

  printf '%s' "$USAGE_BREAKDOWN" | awk -F'\t' -v per="$NANO_PER_AI_CREDIT" '
    NF < 2 { next }
    { n[$1] += $2; c[$1]++; if (!($1 in seen)) { seen[$1]=1; order[++k]=$1 } }
    END {
      for (i = 1; i <= k; i++) {
        label = order[i]
        suffix = (c[label] > 1) ? sprintf("  (x%d)", c[label]) : ""
        printf "                    %-16s %7.3f%s\n", label, n[label] / per, suffix
      }
    }'

  # An unpriced run is reported as unpriced. Printing the partial total as if it
  # were the whole would understate the bill, which is the one direction a cost
  # report must never round.
  [ "$USAGE_INCOMPLETE" = "1" ] &&
    say "                    (one or more runs reported no usage; the total is a lower bound)"
  return 0
}

# run_explain_session <prompt>
# Sets EXPLAIN_RC.
#
# Unlike the two headless shapes this is the developer's own session, so:
#   - custom instructions stay ON. The reviewer disables them because reviewed
#     code must not be able to rewrite the reviewer's brief; this session renders
#     no verdict, and repository context makes its explanations better.
#   - stdio is bound to /dev/tty. A git hook's stdin is closed, and an
#     interactive TUI inheriting that would die on the first keystroke.
#   - there is no timeout. The developer decides when it is finished.
run_explain_session() {
  local prompt="$1"
  MODEL_FLAG=()
  [ -n "${INHOUSECODE_EXPLAIN_MODEL:-}" ] && MODEL_FLAG=(--model "$INHOUSECODE_EXPLAIN_MODEL")

  "$COPILOT_PATH" -i "$prompt" "${MODEL_FLAG[@]}" \
    "${EXPLAIN_PERMISSIONS[@]}" < /dev/tty > /dev/tty 2>&1
  EXPLAIN_RC=$?
  if [ "$EXPLAIN_RC" -ne 0 ]; then
    warn "inhousecode: the explain session exited with status $EXPLAIN_RC."
  fi
  return 0
}

ensure_copilot() {
  COPILOT_PATH="$(resolve_copilot)" || {
    fail "inhousecode: Copilot CLI was not found. Install it: https://github.com/github/copilot-cli"
    return 1
  }
  resolve_timeout || {
    fail "inhousecode: GNU timeout (or gtimeout) is required to bound agent runs."
    return 1
  }
}

# run_review_agent <prompt> <log-path>
# Sets REVIEW_OUTPUT and REVIEW_RC.
run_review_agent() {
  local prompt="$1" log="$2"
  local quiet=(--silent)
  [ "${INHOUSECODE_VERBOSE:-0}" = "1" ] && quiet=()
  copilot_model_flag
  agent_output_format

  "$TIMEOUT_BIN" "$INHOUSECODE_AI_TIMEOUT_SEC" "$COPILOT_PATH" -p "$prompt" \
    "${MODEL_FLAG[@]}" "${quiet[@]}" "${REVIEW_PERMISSIONS[@]}" \
    "${AGENT_OUTPUT_FORMAT[@]}" --no-color > "$log" 2>&1 < /dev/null
  REVIEW_RC=$?
  usage_record "review" "$log"
  REVIEW_OUTPUT="$(strip_cr "$(agent_text "$log")")" || { REVIEW_RC=1; REVIEW_OUTPUT=""; }
}

# run_critique_agent <prompt> <log-path>
# Sets CRITIQUE_OUTPUT and CRITIQUE_RC.
#
# Same read-only shape as the reviewer, and deliberately a *different model*.
# A model critiquing its own findings shares the reasoning that produced them,
# so it agrees with itself far more readily than a stranger would; the whole
# value of a rubber duck is that it did not already believe the conclusion.
run_critique_agent() {
  local prompt="$1" log="$2"
  local quiet=(--silent)
  [ "${INHOUSECODE_VERBOSE:-0}" = "1" ] && quiet=()
  local model=()
  [ -n "${INHOUSECODE_AI_CRITIQUE_MODEL:-}" ] && model=(--model "$INHOUSECODE_AI_CRITIQUE_MODEL")
  agent_output_format

  "$TIMEOUT_BIN" "$INHOUSECODE_AI_TIMEOUT_SEC" "$COPILOT_PATH" -p "$prompt" \
    "${model[@]}" "${quiet[@]}" "${REVIEW_PERMISSIONS[@]}" \
    "${AGENT_OUTPUT_FORMAT[@]}" --no-color > "$log" 2>&1 < /dev/null
  CRITIQUE_RC=$?
  usage_record "second opinion" "$log"
  CRITIQUE_OUTPUT="$(strip_cr "$(agent_text "$log")")" ||
    { CRITIQUE_RC=1; CRITIQUE_OUTPUT=""; }
}

# run_fix_agent <prompt> <log-path>
# Sets FIX_RC. The fix agent gets a longer budget than the reviewer because it
# reads, edits, and re-verifies.
run_fix_agent() {
  local prompt="$1" log="$2" label="${3:-repair}"
  local budget=$((INHOUSECODE_AI_TIMEOUT_SEC * FIX_AGENT_TIMEOUT_MULTIPLIER))
  local quiet=(--silent)
  [ "${INHOUSECODE_VERBOSE:-0}" = "1" ] && quiet=()
  copilot_model_flag
  agent_output_format

  "$TIMEOUT_BIN" "$budget" "$COPILOT_PATH" -p "$prompt" \
    "${MODEL_FLAG[@]}" "${quiet[@]}" "${FIX_PERMISSIONS[@]}" \
    "${AGENT_OUTPUT_FORMAT[@]}" --no-color > "$log" 2>&1 < /dev/null
  FIX_RC=$?
  usage_record "$label" "$log"
  if [ "$FIX_RC" -ne 0 ]; then
    warn "inhousecode: the fix agent exited with status $FIX_RC (log: $log)"
  fi
}

# The standard of craft demanded of any agent that touches this repository's
# code, shared by the repair agents and the explain session so the two cannot
# drift apart.
#
# Three things it has to say, and none of them are obvious to a model:
#
# 1. Match the house style. A technically correct fix written in a dialect the
#    repository does not speak still costs a reviewer their afternoon.
# 2. Keep the developer moving. An agent that stops to ask permission for each
#    of fourteen findings has replaced a blocking gate with a slower one.
# 3. Leave it better than a patch. The fix is read by a person next.
craft_standard() {
  cat <<'EOF'
HOW TO WORK
Work like a senior engineer who owns this code and will be reviewing it on
Monday - not like a linter applying patches.

Respect the repository, not just the finding:
- Read the surrounding code first. Understand why it is shaped the way it is.
- Follow this repository's own conventions and guidelines: AGENTS.md,
  CONTRIBUTING, .github/copilot-instructions.md, the team rulebook, and the
  style already visible in the files you are editing. When house style and your
  own preference disagree, house style wins.
- Match the existing naming, error handling, logging, and structure. A fix that
  reads like it was always there is worth more than a clever one.
- Leave the code better than a patch would: correct, readable, and explained
  where it is not obvious. Comment only what genuinely needs it.

Keep the developer moving:
- Do not block them. Never stop to ask permission for routine, in-scope work,
  and never ask the same question twice.
- If something is genuinely ambiguous, make the most defensible choice, apply
  it, and flag it plainly in your summary rather than halting.
- Never leave the tree half-fixed or broken. If you cannot finish something, say
  what is left and why.
- Their time is the scarce resource here. Spend yours instead.
EOF
}

# The senior-engineer framing applied to every automated repair. Findings are
# facts to be understood, not patches to be pasted.
fix_agent_prompt() {
  local heading="$1" work_order="$2" file_list="$3"
  cat <<EOF
$heading

$(craft_standard)

Rules:
1. Fix the underlying cause, not the symptom. Do not silence a finding with a
   suppression comment, a broad exception handler, or a rename unless that is
   genuinely the correct fix.
2. If a finding is a false positive for this codebase, leave the code as is and
   say so explicitly in your summary, with the reason.
3. Make the smallest correct change. Do not refactor unrelated code, reformat
   files, or change public behavior that is not part of a finding.
4. Preserve existing behavior and tests. If a fix must change behavior, say so.
5. Never stage, commit, push, or run destructive commands.

In-scope files:
$file_list

Findings to resolve:
$work_order

When you are done, print a short summary: what you changed and why, and any
finding you deliberately did not change.
EOF
}
