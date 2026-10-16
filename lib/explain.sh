#!/usr/bin/env bash
#
# The explain handoff.
#
# A verdict tells a developer that something is wrong. It does not tell them
# why, and a gate that blocks without teaching is a gate that gets uninstalled.
# This hands the findings to an interactive Copilot session that opens by
# explaining each one in a fixed, deliberately cramped shape, then stops and
# waits for the developer.
#
# Two halves, and the split is the point:
#
#   the briefing   deterministic. Built here from gate output and the reviewed
#                  source. No model involved, so it is worth
#                  reading even when no session is ever launched.
#   the session    interactive, developer-driven, write-enabled only with the
#                  developer's own approval.
#
# Exports: EXPLAIN_BRIEFING, EXPLAIN_COUNT, EXPLAIN_LAUNCHED

# --- named constants ---------------------------------------------------------
# The briefing outlives the run that wrote it: it deliberately sits beside the
# per-run cache directory, which the EXIT trap deletes.
EXPLAIN_BRIEFING_RELPATH=".inhousecode/cache/last-briefing.md"
EXPLAIN_STOP_LINE="Which would you like to fix? (numbers, or 'all', or ask me anything)"

EXPLAIN_BRIEFING=""
EXPLAIN_COUNT=0
EXPLAIN_LAUNCHED=0
EXPLAIN_TREE_CHANGED=0

explain_briefing_path() {
  printf '%s\n' "$REPO_ROOT/$EXPLAIN_BRIEFING_RELPATH"
}

# Write the briefing without launching anything.
#
# Called on every run that produced findings, including --gate runs that never
# show a prompt. Without this, the one path where a developer most wants to ask
# "what just blocked me?" -- a hook or CI failing non-interactively -- is the
# one path with nothing to replay. Building it costs a single Python call and
# no model, so doing it unconditionally is cheaper than reasoning about when
# it is wanted.
#
# A clean run removes the file rather than leaving it: a stale briefing that
# explains findings the developer already fixed is worse than none.
explain_persist_briefing() {
  [ "${INHOUSECODE_EXPLAIN_ENABLED:-0}" = "1" ] || return 0
  [ -n "$EXPLAIN_BRIEFING" ] && return 0
  if ! build_explain_briefing >/dev/null 2>&1; then
    rm -f "$(explain_briefing_path)" 2>/dev/null
  fi
  return 0
}

# Print the deterministic briefing as part of the normal review result. A real
# terminal gets ANSI highlighting; captured harness output gets the visible red
# marker, so the offending line is never reduced to a file:line summary.
explain_print_finding_details() {
  local color="${1:-auto}" briefing
  briefing="$(explain_briefing_path)"
  [ -s "$briefing" ] || return 0
  printf '\nFinding details:\n\n'
  if ! "${PYTHON_CMD[@]}" "$INHOUSECODE_HOME/lib/finding_view.py" \
      --briefing "$briefing" --all --color "$color"; then
    warn "inhousecode: could not render finding source excerpts."
  fi
  return 0
}

# A cheap snapshot of everything git can see. Compared across the session so a
# passing run is only downgraded when the tree actually moved -- blocking a
# developer who asked a question and changed nothing would teach them not to ask.
explain_tree_fingerprint() {
  git status --porcelain 2>/dev/null | sort
}

# Normalize both gates' findings into one tab-separated list. The shared
# select_findings helper does the de-duplication, which keeps the finding
# markers defined in exactly one place (common.sh) rather than in every
# language that has to read them.
explain_collect_findings() {
  local out="$1"
  : > "$out" || return 1
  if [ -n "${STATIC_OUTPUT:-}" ]; then
    select_findings "$STATIC_OUTPUT" "$STATIC_FINDING_MARKER" all |
      awk -F'\t' 'BEGIN { OFS="\t" } NF>=5 { print "static", $2, $3, $4, $5 }' >> "$out"
  fi
  if [ -n "${AI_OUTPUT:-}" ]; then
    select_findings "$AI_OUTPUT" "$AI_FINDING_MARKER" all |
      awk -F'\t' 'BEGIN { OFS="\t" } NF>=5 { print "review", $2, $3, $4, $5 }' >> "$out"
  fi
  [ -s "$out" ]
}

# Sets EXPLAIN_BRIEFING and EXPLAIN_COUNT. Returns non-zero when there is
# nothing to brief or the briefing could not be written.
build_explain_briefing() {
  local findings briefing count
  findings="${INHOUSECODE_CACHE_ROOT:-$REPO_ROOT/.inhousecode/cache}/explain-findings.tsv"
  briefing="$(explain_briefing_path)"

  explain_collect_findings "$findings" || return 1
  resolve_python || return 1

  count="$("${PYTHON_CMD[@]}" "$INHOUSECODE_HOME/lib/explain.py" \
    --findings "$findings" \
    --out "$briefing" \
    --repo-root "$REPO_ROOT" \
    --target-mode "$TARGET_MODE" \
    --diff-head "${DIFF_HEAD:-HEAD}" \
    --diff-source "${DIFF_SOURCE:-commit}" \
    --context "${INHOUSECODE_EXPLAIN_CONTEXT_LINES:-5}" | tr -d '\r')" || return 1

  EXPLAIN_BRIEFING="$briefing"
  EXPLAIN_COUNT="${count:-0}"
  return 0
}

# The seeded first turn. Brevity is stated as a budget rather than a preference,
# because "be concise" is a suggestion and a word count is not: a wall of text
# fails exactly the way no explanation does -- nobody reads it.
#
# The first layer is deliberately name-free. Whoever opens this session may be
# meeting the codebase today -- a new joiner, or the developer who accepted a
# machine-written change they did not author. An explanation built out of that
# code's own identifiers only works for someone who already knows them, which is
# precisely the reader who did not need the explanation. Name-first, the reader
# spends their attention decoding vocabulary instead of understanding the defect,
# and every unfamiliar name compounds the last one.
#
# So: the concept first, in words that need no tour of the repository; the real
# names second, on request, and never before they have been defined.
explain_session_prompt() {
  local briefing="$1"
  cat <<EOF
Read the briefing at:
  $briefing

It lists every finding inhousecode reported on this change, with the team rule
each one violates and the source lines it points at.

WHO IS READING THIS
Assume the reader is new to this codebase and did not write the change - it may
well have been machine-generated. They do not yet know the function names, class
names, module names, or internal vocabulary of this project, and a sentence
built out of those names tells them nothing. They are not new to programming;
they are new to THIS code. Explain the problem, not the codebase's dialect.

YOUR FIRST TURN
Explain every finding in the briefing, in order, using exactly this block:

[<n>] <SEVERITY> - <file:line> - <category>

  What's wrong   <one sentence, concept level, no identifiers>
  Why it bites   <one sentence: what goes wrong at runtime, and for whom>
  Rule           <the rule text from the briefing, copied, not rewritten>
  Fix            <one sentence describing the change by what it does>

  <the two or three most relevant lines of that finding's source excerpt,
   keeping the > marker on the offending line>

LAYER ONE IS NAME-FREE
In 'What's wrong', 'Why it bites', and 'Fix', do not use any identifier from
this codebase - no function, variable, class, module, config key, or table
names. Refer to things by the job they do:

  not  "convert() divides by the rate returned by rates.get()"
  but  "the conversion step divides by a rate that may be missing"

  not  "load_manifest() is called inside the per-asset loop"
  but  "the file is re-read once per item instead of once overall"

The file:line header is a location, not vocabulary - leave it as it is. The
source excerpt below the block is where the reader meets the real names, in
context, which is the only place names teach anything.

If you cannot state a finding without an identifier, you have not yet found the
concept underneath it. Keep looking: every one of these is a general programming
idea wearing a local name.

BREVITY IS A HARD REQUIREMENT, NOT A PREFERENCE
- Exactly one sentence per field. Never two. Never a paragraph.
- At most 20 words per sentence.
- Plain language. Assume the reader has not seen this pattern before. Do not
  define jargon - avoid it.
- "Rule" is copied from the briefing verbatim. If the briefing says no team rule
  matched, write: No team rule - general review criterion.
- "Fix" describes the change. It does not teach the change.
- No preamble, no introduction, no closing summary. The blocks plus the single
  offer line below are your entire first turn.
- The whole set should fit on one screen. Depth is available if the developer
  asks for it; that is what the rest of this session is for.

END YOUR FIRST TURN WITH THIS OFFER, VERBATIM, AS A SINGLE LINE
Ask me to "name the code" for any finding and I'll walk through it using this
project's actual names, defining each one first.

TONE
You are a senior colleague reading this over their shoulder, not a gate issuing
a verdict. Explain the finding, never judge the person. No praise, no scolding,
no "you should have" - the code under review was very likely machine-generated
anyway. Assume competence and a missing piece of context, and supply it.

THEN STOP
Do not edit a file, run a command, or begin fixing anything on this turn. End
your turn with exactly this line and nothing after it:

$EXPLAIN_STOP_LINE

LAYER TWO - WHEN THEY ASK FOR THE NAMES
Once the reader asks about a specific finding, or asks you to name the code,
switch to this project's real vocabulary. Introduce it, do not assume it:

- Define each name the first time you use it, in one clause, by its role:
  "load_rates - the step that pulls the rate table out of the provider's
  response". Then use the name freely; it has been earned.
- Introduce a few names at a time, in the order the code runs, not in the order
  the file happens to list them.
- Prefer showing the line to describing it. A name next to the line that uses it
  is worth a paragraph about the name.
- Do not define a name you are not about to use, and do not tour the
  architecture. The question was about one finding.
- Repeat the concept sentence from layer one once you reach the defect, so the
  names attach to something the reader already understands.

Go deeper as they keep asking. Follow their level, and never restart from the
concept once they are clearly past it - re-explaining what someone has already
understood reads as condescension.

AFTER THAT
Follow the developer's lead. When you do change code:

$(craft_standard)

Also:
- Fix the underlying cause, not the symptom. Never silence a finding with a
  suppression comment, a broad exception handler, or a rename.
- Make the smallest correct change. Do not refactor or reformat unrelated code.
- If a finding is a false positive here, say so with the reason and change
  nothing.
- Never stage, commit, or push. The developer owns their git history.

Repository under review: $REPO_ROOT
EOF
}

explain_print_fallback() {
  local briefing="$1" reason="$2"
  warn "inhousecode: $reason"
  say ""
  say "  Findings briefing written to:"
  say "    $briefing"
  say ""
  say "  Open a session over it with:"
  say "    inhousecode explain"
  say ""
}

# explain_handoff -- build the briefing and hand it to a session.
# Returns 0 when a session ran, 1 when only the briefing was produced.
explain_handoff() {
  if [ -z "$EXPLAIN_BRIEFING" ] && ! build_explain_briefing; then
    fail "inhousecode: could not build the findings briefing."
    return 1
  fi
  good "inhousecode: briefed $EXPLAIN_COUNT finding(s) -> $EXPLAIN_BRIEFING"
  explain_launch_session "$EXPLAIN_BRIEFING"
}

# Launch the interactive session, or explain why we didn't.
explain_launch_session() {
  local briefing="$1"
  if [ "${INHOUSECODE_EXPLAIN_AUTO_LAUNCH:-0}" != "1" ]; then
    explain_print_fallback "$briefing" \
      "automatic launch is disabled (explain.autoLaunch is false)."
    return 1
  fi
  if ! has_tty; then
    explain_print_fallback "$briefing" \
      "no terminal is attached, so no session was started."
    return 1
  fi
  if ! resolve_harness_bin >/dev/null 2>&1; then
    explain_print_fallback "$briefing" \
      "the ${INHOUSECODE_HARNESS:-copilot} CLI was not found; the briefing above stands on its own."
    return 1
  fi

  step "Opening a ${INHOUSECODE_HARNESS:-copilot} session over these findings..."
  info "  It explains first and edits nothing until you ask. Exit it to come back."
  local before after
  before="$(explain_tree_fingerprint)"
  run_explain_session "$(explain_session_prompt "$briefing")"
  after="$(explain_tree_fingerprint)"
  EXPLAIN_LAUNCHED=1
  [ "$before" = "$after" ] || EXPLAIN_TREE_CHANGED=1
  return 0
}
