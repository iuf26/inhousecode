#!/usr/bin/env bash
#
# Agent invocation layer.
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
#
# The actual CLI binary and flag translation is handled by the harness
# abstraction (lib/harness.sh + lib/harness_*.sh). This file owns cost
# accounting, prompt construction, and the run/classify lifecycle.

# shellcheck source=harness.sh
source "$INHOUSECODE_HOME/lib/harness.sh"

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
USAGE_TOTAL_USD=0
USAGE_RUNS=0
USAGE_BREAKDOWN=""
USAGE_INCOMPLETE=0

usage_reset() {
  USAGE_TOTAL_NANO=0
  USAGE_TOTAL_PREMIUM=0
  USAGE_TOTAL_USD=0
  USAGE_RUNS=0
  USAGE_BREAKDOWN=""
  USAGE_INCOMPLETE=0
}

# agent_text <log> -- the assistant's answer, as text mode would have printed it.
# Falls back to the raw log when the run was not in JSON mode, so the two
# formats stay interchangeable from the caller's point of view.
agent_text() {
  local log="$1"
  # Hermes chat emits plain text plus a session id, not the JSONL envelope used
  # by Copilot and Claude Code. Keep its response intact so the gate can parse
  # the review contract directly.
  if [ "${INHOUSECODE_HARNESS:-}" = "hermes" ]; then
    cat "$log" 2>/dev/null
    return 0
  fi
  if [ -z "${PYTHON_CMD:-}" ]; then
    cat "$log" 2>/dev/null
    return 0
  fi
  "${PYTHON_CMD[@]}" "$INHOUSECODE_HOME/lib/usage.py" --log "$log" --mode text 2>/dev/null
}

# usage_record <label> <log> -- add one agent run to the running total.
#
# usage.py's output is nano<TAB>premium<TAB>usd. Copilot reports nano-AIU;
# Claude Code and Hermes report USD directly. Both are accumulated so the
# summary can print whichever ended up non-zero, without the caller needing
# to know which harness produced the log.
usage_record() {
  local label="$1" log="$2" raw nano premium usd
  USAGE_RUNS=$((USAGE_RUNS + 1))
  if [ -z "${PYTHON_CMD:-}" ]; then
    USAGE_INCOMPLETE=1
    return 0
  fi
  raw="$("${PYTHON_CMD[@]}" "$INHOUSECODE_HOME/lib/usage.py" --log "$log" --mode usage 2>/dev/null)" || raw=""
  nano="$(printf '%s' "$raw" | awk -F'	' '{ print $1 }')"
  premium="$(printf '%s' "$raw" | awk -F'	' '{ print $2 }')"
  usd="$(printf '%s' "$raw" | awk -F'	' '{ print $3 }')"
  case "$nano" in
    ''|*[!0-9]*) USAGE_INCOMPLETE=1; return 0 ;;
  esac
  case "$premium" in
    ''|*[!0-9]*) premium=0 ;;
  esac
  case "$usd" in
    ''|*[!0-9.]*) usd=0 ;;
  esac
  USAGE_TOTAL_NANO=$((USAGE_TOTAL_NANO + nano))
  USAGE_TOTAL_PREMIUM=$((USAGE_TOTAL_PREMIUM + premium))
  USAGE_TOTAL_USD="$(awk -v a="$USAGE_TOTAL_USD" -v b="$usd" 'BEGIN { printf "%.6f", a + b }')"
  USAGE_BREAKDOWN="${USAGE_BREAKDOWN}${label}	${nano}	${premium}	${usd}
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
#
# Nano-AIU (Copilot) and USD (Claude Code, Hermes) are reported in whichever
# unit is actually non-zero -- converting between them would be inventing an
# exchange rate no CLI ever claimed.
print_usage_summary() {
  [ "$USAGE_RUNS" -gt 0 ] || return 0

  say ""
  if [ "$USAGE_TOTAL_NANO" -gt 0 ]; then
    say "  Cost            : $(usage_credits "$USAGE_TOTAL_NANO") AI credits across $USAGE_RUNS agent run(s)"
  else
    say "  Cost            : \$$(printf '%.4f' "$USAGE_TOTAL_USD") across $USAGE_RUNS agent run(s)"
  fi
  [ "$USAGE_TOTAL_PREMIUM" -gt 0 ] &&
    say "                    $USAGE_TOTAL_PREMIUM premium request(s)"

  if [ "$USAGE_TOTAL_NANO" -gt 0 ]; then
    printf '%b' "$USAGE_BREAKDOWN" | awk -F'	' -v per="$NANO_PER_AI_CREDIT" '
      NF < 3 { next }
      { n[$1] += $2; c[$1]++; if (!($1 in seen)) { seen[$1]=1; order[++k]=$1 } }
      END {
        for (i = 1; i <= k; i++) {
          label = order[i]
          suffix = (c[label] > 1) ? sprintf("  (x%d)", c[label]) : ""
          printf "                    %-16s %7.3f%s\n", label, n[label] / per, suffix
        }
      }'
  else
    printf '%b' "$USAGE_BREAKDOWN" | awk -F'	' '
      NF < 4 { next }
      { n[$1] += $4; c[$1]++; if (!($1 in seen)) { seen[$1]=1; order[++k]=$1 } }
      END {
        for (i = 1; i <= k; i++) {
          label = order[i]
          suffix = (c[label] > 1) ? sprintf("  (x%d)", c[label]) : ""
          printf "                    %-16s $%6.4f%s\n", label, n[label], suffix
        }
      }'
  fi

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
  local model=""
  [ -n "${INHOUSECODE_EXPLAIN_MODEL:-}" ] && model="$INHOUSECODE_EXPLAIN_MODEL"

  harness_explain_cmd "$prompt" "$model"
  EXPLAIN_RC="$HARNESS_RC"
  if [ "$EXPLAIN_RC" -ne 0 ]; then
    warn "inhousecode: the explain session exited with status $EXPLAIN_RC."
  fi
  return 0
}

ensure_copilot() {
  ensure_harness
}

# run_review_agent <prompt> <log-path>
# Sets REVIEW_OUTPUT and REVIEW_RC.
run_review_agent() {
  local prompt="$1" log="$2"
  local model=""
  [ -n "${INHOUSECODE_AI_MODEL:-}" ] && model="$INHOUSECODE_AI_MODEL"

  harness_review_cmd "$prompt" "$log" "$INHOUSECODE_AI_TIMEOUT_SEC" \
    "$model" "${INHOUSECODE_VERBOSE:-0}"
  REVIEW_RC="$HARNESS_RC"
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
  local model=""
  [ -n "${INHOUSECODE_AI_CRITIQUE_MODEL:-}" ] && model="$INHOUSECODE_AI_CRITIQUE_MODEL"

  harness_review_cmd "$prompt" "$log" "$INHOUSECODE_AI_TIMEOUT_SEC" \
    "$model" "${INHOUSECODE_VERBOSE:-0}"
  CRITIQUE_RC="$HARNESS_RC"
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
  local model=""
  [ -n "${INHOUSECODE_AI_MODEL:-}" ] && model="$INHOUSECODE_AI_MODEL"

  harness_fix_cmd "$prompt" "$log" "$budget" "$model" "${INHOUSECODE_VERBOSE:-0}"
  FIX_RC="$HARNESS_RC"
  usage_record "$label" "$log"
  if [ "$FIX_RC" -ne 0 ]; then
    warn "inhousecode: the fix agent exited with status $FIX_RC (log: $log)"
  fi
}

# run_discover_agent <prompt> <log-path>
# Sets DISCOVER_RC. Used only by `inhousecode discover`: read + shell, no
# file-edit tool. It may call `inhousecode memory candidate add`, but it cannot
# edit repository files or call OpenViking directly.
run_discover_agent() {
  local prompt="$1" log="$2" label="${3:-discover}"
  local budget=$((INHOUSECODE_AI_TIMEOUT_SEC * FIX_AGENT_TIMEOUT_MULTIPLIER))
  local model=""
  [ -n "${INHOUSECODE_AI_MODEL:-}" ] && model="$INHOUSECODE_AI_MODEL"

  harness_discover_cmd "$prompt" "$log" "$budget" "$model" "${INHOUSECODE_VERBOSE:-0}"
  DISCOVER_RC="$HARNESS_RC"
  usage_record "$label" "$log"
  if [ "$DISCOVER_RC" -ne 0 ]; then
    warn "inhousecode: the discovery agent exited with status $DISCOVER_RC (log: $log)"
  fi
}

# run_draft_agent <prompt> <log-path>
# Sets DRAFT_OUTPUT and DRAFT_RC. A short, read-only, headless call used to
# turn a developer's terse "we don't do that here" into one well-formed team
# memory line. It cannot write anything: the human approves the draft and the
# memory policy performs the only write. Deliberately reuses the read-only review
# shape so a drafting call has no more power than a review does.
run_draft_agent() {
  local prompt="$1" log="$2"
  local model=""
  [ -n "${INHOUSECODE_AI_MODEL:-}" ] && model="$INHOUSECODE_AI_MODEL"

  harness_review_cmd "$prompt" "$log" "$INHOUSECODE_AI_TIMEOUT_SEC" \
    "$model" "${INHOUSECODE_VERBOSE:-0}"
  DRAFT_RC="$HARNESS_RC"
  usage_record "memory draft" "$log"
  DRAFT_OUTPUT="$(strip_cr "$(agent_text "$log")")" || { DRAFT_RC=1; DRAFT_OUTPUT=""; }
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
  CONTRIBUTING, .github/copilot-instructions.md, approved review knowledge
  supplied with the finding, and the style already visible in the files you are
  editing. When house style and your own preference disagree, house style wins.
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
