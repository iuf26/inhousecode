#!/usr/bin/env bash
#
# Phase 2 — the judgment gate.
#
# The static gate proves the change is free of mechanically detectable defects.
# This gate asks the question a tool cannot: does the change actually do what it
# claims, and does it respect the rules this team has written down?
#
# Blocking findings (CRITICAL/HIGH) are repaired automatically and re-reviewed.
# Everything the automatic pass leaves behind is then offered to the developer
# as one numbered list — blocking or not, they pick what to fix.
#
# Exports: AI_STATUS (pass|fail|unavailable|skipped), AI_OUTPUT, AI_ERROR,
#          AI_FIX_ROUNDS

AI_STATUS="not-run"
AI_OUTPUT=""
AI_ERROR=""
AI_FIX_ROUNDS=0
# Counts developer-driven triage rounds, so "fix, see what that surfaced, fix
# again" stays bounded by the same budget as automatic repair.
AI_PICK_ROUNDS=0

ai_write_inputs() {
  local diff_path="$INHOUSECODE_CACHE_ROOT/review.diff"
  case "$TARGET_MODE" in
    staged)   git diff --cached --no-ext-diff --unified=80 > "$diff_path" ;;
    worktree) git diff HEAD --no-ext-diff --unified=80 > "$diff_path" ;;
    diff)
      # With repairs enabled the working tree carries the fixes, so the diff is
      # taken against it; otherwise the reviewed commit is the exact subject.
      if [ "${DIFF_SOURCE:-commit}" = "worktree" ]; then
        git diff --no-ext-diff --unified=80 "${DIFF_MERGE_BASE:-}" > "$diff_path"
      else
        git diff --no-ext-diff --unified=80 "${DIFF_MERGE_BASE:-}" "${DIFF_HEAD:-HEAD}" > "$diff_path"
      fi
      ;;
    path)     : > "$diff_path" ;;
  esac || {
    AI_ERROR="could not prepare the review diff"
    return 1
  }
  AI_DIFF_PATH="$diff_path"
  ai_write_commit_log
  ai_write_intent_brief
  ai_write_impact_report
  ai_resolve_source_root
}

# The pull-request description is the change's own specification: the author
# telling reviewers what this branch delivers. Nothing else the gate sees states
# the intent that plainly -- the diff shows what happened, the commit log shows
# it commit by commit, and neither says what was promised.
#
# Written out so the reviewer can check the branch against it claim by claim. A
# promise the code does not keep is a defect that no static analyzer and no
# diff-only reviewer can possibly find, and it is the single most common reason
# a merged PR does not do what its reviewer thought they approved.
ai_write_intent_brief() {
  AI_INTENT_PATH=""
  [ "${INHOUSECODE_AI_VERIFY_INTENT:-1}" = "1" ] || return 0
  [ -n "${PR_BODY:-}" ] || return 0

  local intent_path="$INHOUSECODE_CACHE_ROOT/pr-description.md"
  {
    printf '# PR #%s: %s\n\n' "${PR_ID:-?}" "${PR_TITLE:-untitled}"
    printf '%s\n' "$PR_BODY"
  } > "$intent_path" 2>/dev/null || return 0
  [ -s "$intent_path" ] && AI_INTENT_PATH="$intent_path"
  return 0
}

# Who else depends on what this change touched. See lib/impact.sh: this is the
# half of "does it break anything?" that lives outside the diff.
ai_write_impact_report() {
  AI_IMPACT_PATH=""
  [ "${INHOUSECODE_AI_IMPACT_ANALYSIS:-1}" = "1" ] || return 0
  [ "$TARGET_MODE" = "path" ] && return 0

  impact_write_report "$INHOUSECODE_CACHE_ROOT/impact.txt" >/dev/null 2>&1 || return 0
  AI_IMPACT_PATH="$IMPACT_PATH"
  return 0
}

# The commit messages on the branch are the author's stated intent. A reviewer
# who can compare "what this claims to do" against "what the code does" catches
# a class of problem the diff alone never reveals.
ai_write_commit_log() {
  AI_COMMITS_PATH=""
  [ "$TARGET_MODE" = "diff" ] || return 0
  [ -n "${DIFF_MERGE_BASE:-}" ] || return 0

  local commits_path="$INHOUSECODE_CACHE_ROOT/review-commits.txt"
  git log --no-merges --date=short --format='%h %ad %an: %s%n%w(0,4,4)%b' \
    "${DIFF_MERGE_BASE}..${DIFF_HEAD:-HEAD}" > "$commits_path" 2>/dev/null || return 0
  [ -s "$commits_path" ] && AI_COMMITS_PATH="$commits_path"
  return 0
}

# The reviewer reads whole files for context around the diff. When the commit
# under review is not the one checked out — reviewing a pull request without
# switching branches — the working tree is the wrong source, so the reviewed
# blobs are materialized and the reviewer is pointed at those instead.
ai_resolve_source_root() {
  AI_SOURCE_ROOT="$REPO_ROOT"
  [ "$TARGET_MODE" = "diff" ] || return 0
  [ "${DIFF_SOURCE:-commit}" = "commit" ] || return 0
  local head_rev="${DIFF_HEAD:-HEAD}"
  [ "$head_rev" != "$(git rev-parse --verify --quiet HEAD)" ] || return 0

  local tree="$INHOUSECODE_CACHE_ROOT/review-tree" file
  rm -rf -- "$tree" && mkdir -p "$tree" || {
    AI_ERROR="could not materialize the reviewed commit"
    return 1
  }
  while IFS= read -r file; do
    [ -n "$file" ] || continue
    git cat-file -e "$head_rev:$file" 2>/dev/null || continue   # deleted by the PR
    mkdir -p "$tree/$(dirname "$file")" || continue
    git show "$head_rev:$file" > "$tree/$file" 2>/dev/null || continue
  done < "$INHOUSECODE_CACHE_ROOT/scan-files.txt"
  AI_SOURCE_ROOT="$tree"
  return 0
}

ai_build_prompt() {
  local skill="$INHOUSECODE_HOME/skills/code-review/SKILL.md"
  local checklist="$INHOUSECODE_HOME/skills/code-review/references/code-review-checklist.md"
  local rulebook="$REPO_ROOT/$INHOUSECODE_RULEBOOK"
  local rulebook_line="Team rulebook: this repository has none. Judge against the criteria below only."
  [ -f "$rulebook" ] &&
    rulebook_line="Team rulebook (AUTHORITATIVE - read it in full and check every active guideline): $rulebook"

  local contract
  contract="$(ai_output_contract)"

  local source_line="Review source: the change described by the diff below."
  if [ "$TARGET_MODE" = "diff" ]; then
    source_line="Review source: a pull request${PR_ID:+ (#$PR_ID${PR_TITLE:+ - $PR_TITLE})} - every
commit the branch adds on top of '${DIFF_BASE:-the base branch}'. Judge the branch as a
whole, as a human reviewer approving or rejecting it would."
  fi

  # In a report-only review nothing was repaired, so the reviewer must not be
  # told the Semgrep findings are already gone.
  local semgrep_line="Semgrep already ran over this change and its findings were resolved. Do not
re-report mechanically detectable lint or pattern matches; report what a tool
cannot see: intent, correctness, contracts, and the team rulebook."
  [ "${INHOUSECODE_STATIC_AUTOFIX:-0}" = "1" ] ||
    semgrep_line="Semgrep already ran over this change and its findings were reported separately.
Do not re-report mechanically detectable lint or pattern matches; report what a
tool cannot see: intent, correctness, contracts, and the team rulebook."

  local critique="$INHOUSECODE_HOME/skills/code-review/references/finding-critique.md"
  local reference_line="Reference material, richer detail on the same method. Read it if you can;
if a read is denied or the file is missing, continue without it - the criteria
above are sufficient and the output contract still applies:
- $skill
- $checklist
- $critique"

  local commits_line=""
  [ -n "${AI_COMMITS_PATH:-}" ] &&
    commits_line="
- Branch commit log, the author's stated intent: $AI_COMMITS_PATH"

  local intent_line=""
  [ -n "${AI_INTENT_PATH:-}" ] &&
    intent_line="
- Pull-request description, what the author says this delivers: $AI_INTENT_PATH"

  local impact_line=""
  [ -n "${AI_IMPACT_PATH:-}" ] &&
    impact_line="
- Blast radius, who else depends on the contracts this change touched: $AI_IMPACT_PATH"

  local intent_task=""
  [ -n "${AI_INTENT_PATH:-}" ] && intent_task="$(ai_intent_task)"

  local impact_task=""
  [ -n "${AI_IMPACT_PATH:-}" ] && impact_task="$(ai_impact_task)"

  case "$TARGET_MODE" in
    path)
      AI_PROMPT="You are a senior code reviewer running as an automated gate. Review the full
contents of every file listed below.

Review source: path review of '$TARGET_PATH'
In-scope files (read this file for the list): $INHOUSECODE_CACHE_ROOT/scan-files.txt
Repository root: $REPO_ROOT
$rulebook_line

$reference_line

$contract"
      ;;
    *)
      AI_PROMPT="You are a senior code reviewer running as an automated gate. Review the supplied
change.

$source_line

Read only these inputs:
- Diff: $AI_DIFF_PATH
- In-scope files (read this file for the list): $INHOUSECODE_CACHE_ROOT/scan-files.txt
- Reviewed source root: ${AI_SOURCE_ROOT:-$REPO_ROOT}$commits_line$intent_line$impact_line
$rulebook_line

Paths inside the reviewed source root are repository-relative. Report every
finding with its repository-relative path, never an absolute one.

Judge only the changed lines and their direct consequences. Pre-existing
problems in untouched code are out of scope.

Where a commit log is supplied, treat it as a claim, not as evidence. If the
code does something the messages do not describe, or fails to do something they
promise, that gap is itself a finding.
$intent_task$impact_task
$semgrep_line

$reference_line

$contract"
      ;;
  esac
}

# The description is a specification, and this is the acceptance test against
# it. Stated as a checklist the reviewer must complete and report, because
# "check it does what it says" without a required output is advice a model
# quietly skips when the diff is large.
ai_intent_task() {
  cat <<'EOF'

VERIFY THE CHANGE AGAINST ITS OWN DESCRIPTION
The pull-request description is the author's specification. Before you judge the
code, turn it into a checklist and complete it.

1. Extract every checkable claim the description makes about THIS change: each
   promised behavior, fix, migration, config key, guarantee, and removal. A
   claim is checkable when you could point at code and say "there it is, or it
   is not there".
2. Ignore everything that is not a claim about this change: background,
   motivation, rollout notes, screenshots, review instructions, and any work the
   description explicitly assigns to another PR in a series ("part 2 will...",
   "follow-up", "tracked separately"). Judging a stacked PR against its
   siblings' promises produces nothing but false failures.
3. For each surviving claim, find the code that delivers it and decide:
     MET           the code plainly does it. Cite the file:line that proves it.
     PARTIAL       it does some of it, or does it for only some of the cases
                   the claim covers. Say precisely what is missing.
     UNMET         you cannot find code in this change that does it.
     UNVERIFIABLE  it cannot be judged from this diff (infrastructure, a
                   dashboard, a manual step). Say why, and move on.
4. Then look the other way: behavior this change introduces that the description
   never mentions. An undocumented behavior change is how a reviewer approves
   something they did not know they were approving.

Emit one ##CR-CLAIM## line per claim (format below). Then, additionally:
- every UNMET claim becomes a finding, category 'pr-claim-unmet'. HIGH when the
  description presents it as delivered here; MEDIUM when the wording is loose
  enough that a reasonable author meant it as intent rather than a promise.
- every PARTIAL claim becomes a MEDIUM finding, category 'pr-claim-partial'.
- undocumented behavior change becomes a MEDIUM finding, category
  'undocumented-change' -- unless it is breaking, which the section below governs.
Do not invent claims to fill the checklist. A description that makes two
checkable claims yields two lines.
EOF
}

# Breaking-change analysis, framed as the procedure a senior engineer actually
# runs. The knowledge that separates them from a careful junior is not that they
# are more suspicious -- it is that they know a change to a *shared contract* is
# a different kind of event from a change to a leaf, and they go and look at the
# other implementations before they say yes.
ai_impact_task() {
  cat <<'EOF'

DECIDE WHETHER THIS CHANGE BREAKS ANYTHING
You have been given a blast-radius map: every contract this change touched and
who else in the repository still depends on it. It is context, not findings.
Work through it the way an engineer who owns this codebase would.

For each contract in the map that is 'removed' or 'modified':
1. State what its callers were promised BEFORE this change - the signature, the
   return shape, the defaults, the error behavior, the ordering, the side
   effects, the persisted or serialized format.
2. State what they are promised AFTER it.
3. If those differ in any way a caller could observe, open each referenced call
   site and check whether it still holds. Name the ones that do not.

Pay particular attention to changes that swap out or extend an existing
STRATEGY, policy, handler, or interface implementation. These break silently,
because nothing fails to compile:
- Every other implementation of the same interface must still satisfy it. A new
  required method, a changed signature, or a new precondition breaks the
  siblings the diff never touched - go and check them.
- A changed default, threshold, or selection rule silently re-routes callers who
  never opted in. Who was relying on the old default?
- If the new strategy becomes the primary path, what happens to the old one:
  still reachable, still tested, or now dead code that will rot?
- A behavior that used to be total (always applied) becoming conditional, or the
  reverse, changes results for existing inputs even though every call site
  compiles unchanged.

Also check, when the change touches them:
- persisted data, migrations, and serialized formats: can code at the previous
  version still read what this writes, and can this read what is already stored?
- config keys and environment variables: renamed or removed without a fallback
  is a break for every deployment that already sets the old one.
- public API surface, exit codes, log formats, and CLI flags that something
  outside this repository may depend on.
- concurrency and ordering assumptions a caller may hold but never state.

Report a break as a finding with category 'breaking-change': HIGH when a
specific existing caller, implementation, or stored record is wrong after this
change, and you can name it. If the map shows a contract is used
repository-wide, the bar for calling its behavior change safe is correspondingly
higher - say what you checked.

Do NOT report a finding merely because a symbol has many references. A
compatible change to a widely used helper is still compatible. The finding is
the incompatibility, and you must be able to name the caller it breaks.
EOF
}

# The claim-line format, emitted only when a description was supplied. Kept out
# of the base contract so a review with nothing to check against is never told
# about a line shape it has no reason to produce.
ai_claim_contract() {
  [ -n "${AI_INTENT_PATH:-}" ] || return 0
  cat <<EOF
INTENT CHECKLIST LINES - ALSO REQUIRED
Emit one line per claim you extracted from the pull-request description, in this
exact shape, with real TAB characters between the four fields:

$AI_CLAIM_MARKER<TAB>STATUS<TAB>the claim, in your own words<TAB>evidence

  STATUS    exactly one of MET, PARTIAL, UNMET, UNVERIFIABLE
  claim     one short line. No tabs, no line breaks.
  evidence  file:line that proves it for MET, or what is missing otherwise.

These lines are not findings and carry no severity. They do not replace the
$AI_FINDING_MARKER lines that an UNMET or PARTIAL claim also requires.

EOF
}

# The machine-readable contract. This is deliberately restated in full inside
# every prompt rather than being left to the skill file: the reviewer may be
# unable to read files outside the repository (content exclusion policies,
# denied permissions, a relocated checkout), and a reviewer that silently drops
# the output format is indistinguishable from a reviewer that found nothing.
ai_output_contract() {
  cat <<EOF
SEVERITY RUBRIC
  CRITICAL  exploitable vulnerability, data loss, or corruption. Never a
            rulebook rule's severity - a rule tops out at HIGH.
  HIGH      a bug that will surface in production, or a rulebook guideline
            violated at its default severity (no marker, or explicit (HIGH)).
  MEDIUM    a real weakness: missing validation, a poor contract, an
            unmeaningful test, a performance trap, or a rulebook guideline
            marked (MEDIUM).
  LOW       polish. Naming, clarity, small idiom issues, or a rulebook
            guideline marked (LOW).
CRITICAL and HIGH are blocking. MEDIUM and LOW are not, and must never be
promoted to blocking. Formatting and style never exceed MEDIUM. A rulebook
rule's own marker sets its severity - use exactly what the rule declares,
never upgrade or downgrade it.

OUTPUT CONTRACT - THIS IS NOT OPTIONAL
Emit one line per finding, in this exact shape, with real TAB characters
between the five fields and nothing else on the line:

$AI_FINDING_MARKER<TAB>SEVERITY<TAB>file:line<TAB>category<TAB>one-line fix

  SEVERITY   exactly one of CRITICAL, HIGH, MEDIUM, LOW
  file:line  repository-relative path and the line number
  category   two or three words, or the rulebook rule id it violates
  fix        one imperative sentence, on a single line

$(ai_claim_contract)
CRITIQUE YOUR FINDINGS BEFORE YOU EMIT THEM
Everything you find is a DRAFT finding. Before writing a single
$AI_FINDING_MARKER line, argue the opposite case for each draft finding:

  1. Name the exact line and the concrete mechanism by which it misbehaves.
     'This looks unsafe' is not a mechanism - drop it.
  2. Confirm this change introduces it. Pre-existing code the change only sits
     next to is out of scope - drop it.
  3. Look for the guard, validation, caller contract, or type constraint that
     already makes it moot. If one exists, drop it.
  4. Keep CRITICAL or HIGH only if you can state the origin line, the runtime
     consequence, and why no existing guard prevents it. Otherwise downgrade it
     to MEDIUM, or drop it if the mechanism does not hold.

Bias toward dropping and downgrading. A false positive costs more than a missed
MEDIUM: it is what gets this gate turned off. Emit only the survivors, at their
post-critique severity, and never emit the critique itself.

Then, as the LAST non-empty line of your entire response, print exactly one of:

$AI_VERDICT_PREFIX: FAIL     (if there is at least one CRITICAL or HIGH finding)
$AI_VERDICT_PREFIX: PASS     (only if there are none)

Hard requirements:
- Prose summaries do not count. Every finding you mention in prose MUST also
  appear as a $AI_FINDING_MARKER line, or it will be discarded.
- Never write '$AI_VERDICT_PREFIX: PASS' while a CRITICAL or HIGH line exists.
- Emit the verdict line even when you found nothing at all.
- Do not wrap the finding or verdict lines in code fences, quotes, or bullets.
- Do not run shell commands, modify files, or ask questions.
EOF
}

# The critic gets the draft findings verbatim, already in contract shape, so a
# survivor is copied rather than re-derived -- re-derivation is where a second
# model invents a third set of findings nobody asked for.
ai_critique_prompt() {
  local reference="$INHOUSECODE_HOME/skills/code-review/references/finding-critique.md"
  local rulebook="$REPO_ROOT/$INHOUSECODE_RULEBOOK"
  local rulebook_line="Team rulebook: this repository has none."
  [ -f "$rulebook" ] && rulebook_line="Team rulebook (what the findings were judged against): $rulebook"
  local source_line="Reviewed source root: ${AI_SOURCE_ROOT:-$REPO_ROOT}"
  [ "$TARGET_MODE" = "path" ] && source_line="Repository root: $REPO_ROOT"
  local diff_line=""
  [ -n "${AI_DIFF_PATH:-}" ] && diff_line="
- The change under review: $AI_DIFF_PATH"

  cat <<EOF
You are a second reviewer giving an independent opinion on ANOTHER reviewer's
findings. You did not write them and you owe them nothing. Your value is
precisely that you do not already believe them.

$source_line$diff_line
- In-scope files (read this file for the list): $INHOUSECODE_CACHE_ROOT/scan-files.txt
$rulebook_line

Reference material, the method in full. Read it if you can; if the read is
denied or the file is missing, continue without it - the instructions below are
sufficient and the output contract still applies:
- $reference

YOU HAVE EXACTLY TWO JOBS.

JOB 1 - CHECK THE FINDINGS
For each draft finding below, read the cited line and enough surrounding code to
settle the question, then decide:

  CONFIRM    real, introduced by this change, unguarded, honestly severed.
             Keep it, unchanged.
  DOWNGRADE  real but less impactful than drafted - guarded on the common path,
             bounded input, non-production path. Keep it at the lower severity.
  DROP       not real, out of scope, already handled by an existing guard, or
             not groundable in a specific line of the reviewed change.

You are strictly subtractive. Do not add findings, do not go hunting for new
ones, and do not raise a severity. A finding you cannot ground in a line of the
reviewed change is a DROP, not a MEDIUM. Bias toward DROP and DOWNGRADE: two
survivors that are certainly true beat six that are probably true.

DROP MEANS DISPROVED, NOT UNREAD
Only drop a finding after you have actually read the code and it did not hold.
If a file cannot be opened, a read is denied, or the cited path does not resolve
on disk, CONFIRM the finding unchanged and say nothing further about it. Being
unable to check a finding is not evidence against it, and a pass that empties
the report because it could not see the code would turn a failing review into a
clean one - the one outcome this pass must never produce.

Before a finding stays CRITICAL or HIGH it must have all three of: the specific
line where the defect originates, the concrete runtime consequence, and the
reason no existing guard prevents it. Missing any one - DOWNGRADE to MEDIUM, or
DROP if the mechanism itself does not hold.

JOB 2 - REPORT MISDECLARATIONS
Separately from the verdict above, flag every finding that is wrongly STATED
rather than simply wrong, and that you cannot fix by dropping or downgrading it.
The original reviewer will correct these; you must not rewrite them yourself.

  WRONG-LINE    the cited file:line does not contain the code described.
  WRONG-SEVERITY the severity does not follow from the mechanism, in either
                direction, and the correct one is not simply lower.
  UNPROVEN      the mechanism is asserted rather than demonstrated, but the
                concern may well be real once properly grounded.
  MISCATEGORIZED the category or rulebook rule id does not match the defect.
  DUPLICATE     two findings describe one defect; say which is the origin.
  VAGUE-FIX     the fix is not a specific, imperative, single action.

Do not raise a misdeclaration for a finding you DROPPED - it is gone.

OUTPUT CONTRACT - THIS IS NOT OPTIONAL
First, one line per SURVIVING finding, in this exact shape, with real TAB
characters between the five fields and nothing else on the line. Copy confirmed
findings verbatim; write downgraded ones with the lower severity:

$AI_FINDING_MARKER<TAB>SEVERITY<TAB>file:line<TAB>category<TAB>one-line fix

Then, one line per misdeclaration, with real TAB characters between the five
fields:

$AI_MISDECL_MARKER<TAB>ISSUE<TAB>file:line<TAB>what is wrong<TAB>required correction

  ISSUE        exactly one of WRONG-LINE, WRONG-SEVERITY, UNPROVEN,
               MISCATEGORIZED, DUPLICATE, VAGUE-FIX
  file:line    the finding you are correcting, as it was cited
  what is wrong one sentence, on a single line
  correction   what the reviewer must do to state it correctly, imperative

Then, as the LAST non-empty line of your entire response, print exactly one of:

$AI_VERDICT_PREFIX: FAIL     (if at least one surviving finding is CRITICAL or HIGH)
$AI_VERDICT_PREFIX: PASS     (only if there are none)

Hard requirements:
- Emit the verdict line even when every finding was dropped.
- Never write '$AI_VERDICT_PREFIX: PASS' while a surviving CRITICAL or HIGH line exists.
- Do not emit your reasoning, the dropped findings, or a verdict table.
- Do not wrap these lines in code fences, quotes, or bullets.
- Do not run shell commands, modify files, or ask questions.

DRAFT FINDINGS UNDER REVIEW
$(select_findings "$AI_OUTPUT" "$AI_FINDING_MARKER" all)
EOF
}

# The reviewer corrects its own report. Only the misdeclarations are in play:
# reopening the whole review here would discard the critique that was just paid
# for, and turn a bounded correction into an unbounded second review.
ai_revision_prompt() {
  local critique="$1"
  local source_line="Reviewed source root: ${AI_SOURCE_ROOT:-$REPO_ROOT}"
  [ "$TARGET_MODE" = "path" ] && source_line="Repository root: $REPO_ROOT"
  local diff_line=""
  [ -n "${AI_DIFF_PATH:-}" ] && diff_line="
- The change under review: $AI_DIFF_PATH"

  cat <<EOF
You are the senior code reviewer who produced the report below. A second
reviewer, working independently, has already dropped and downgraded what it
could. What remains are findings it judged to be wrongly STATED - it will not
rewrite them, because that is your report to correct.

$source_line$diff_line
- In-scope files (read this file for the list): $INHOUSECODE_CACHE_ROOT/scan-files.txt

For each correction below, go back to the code and do exactly one of:
- restate the finding correctly - the right line, severity, category, or a
  specific imperative fix - and keep it;
- ground the mechanism concretely, if it is real but was only asserted;
- drop the finding, if going back to the code shows it does not hold.

Correcting a finding means proving it, not rewording it. If you cannot point at
the line and name what goes wrong at runtime, drop it. Dropping is a legitimate
and frequently correct answer here.

Do not add new findings, do not re-review the change, and do not restore
anything the second reviewer dropped.

OUTPUT CONTRACT - THIS IS NOT OPTIONAL
Emit the COMPLETE corrected report: one line per finding that survives, both the
ones you corrected and the ones nobody objected to, in this exact shape, with
real TAB characters between the five fields and nothing else on the line:

$AI_FINDING_MARKER<TAB>SEVERITY<TAB>file:line<TAB>category<TAB>one-line fix

Then, as the LAST non-empty line of your entire response, print exactly one of:

$AI_VERDICT_PREFIX: FAIL     (if there is at least one CRITICAL or HIGH finding)
$AI_VERDICT_PREFIX: PASS     (only if there are none)

Hard requirements:
- Emit the verdict line even when every finding was dropped.
- Never write '$AI_VERDICT_PREFIX: PASS' while a CRITICAL or HIGH line exists.
- Do not emit your reasoning or the corrections themselves.
- Do not wrap these lines in code fences, quotes, or bullets.
- Do not run shell commands, modify files, or ask questions.

CURRENT FINDINGS
$(select_findings "$AI_OUTPUT" "$AI_FINDING_MARKER" all)

CORRECTIONS REQUIRED
$(lines_with_marker "$critique" "$AI_MISDECL_MARKER" 5)
EOF
}

# ai_classify [exit-status]
# Defaults to the reviewer's own status. The critique pass passes its own, so
# that a report is never classified against the exit code of a different run.
ai_classify() {
  local rc="${1:-$REVIEW_RC}"
  local verdict blocking
  verdict="$(gate_verdict "$AI_OUTPUT")"
  blocking="$(count_findings "$AI_OUTPUT" "$AI_FINDING_MARKER" blocking)"

  if [ "$rc" -ne 0 ]; then
    AI_STATUS="unavailable"
    if [ "$rc" -eq "$TIMEOUT_EXIT_STATUS" ]; then
      AI_ERROR="the reviewer timed out after ${INHOUSECODE_AI_TIMEOUT_SEC}s"
    else
      AI_ERROR="the reviewer exited with status $rc"
    fi
  elif ! validate_gate_output "$AI_OUTPUT" "$AI_FINDING_MARKER" "$AI_VERDICT_PREFIX"; then
    AI_STATUS="unavailable"
    AI_ERROR="the reviewer emitted a malformed report"
  elif [ "$verdict" = "$AI_VERDICT_PREFIX: PASS" ] && [ "$blocking" -eq 0 ]; then
    AI_STATUS="pass"
  elif [ "$verdict" = "$AI_VERDICT_PREFIX: FAIL" ] && [ "$blocking" -gt 0 ]; then
    AI_STATUS="fail"
  else
    AI_STATUS="unavailable"
    AI_ERROR="the reviewer produced no valid verdict"
  fi
}

ai_review_once() {
  local log="$INHOUSECODE_CACHE_ROOT/ai-review-$AI_FIX_ROUNDS.log"
  ai_build_prompt
  info "AI review: running (timeout ${INHOUSECODE_AI_TIMEOUT_SEC}s, log: $log)"
  run_review_agent "$AI_PROMPT" "$log"
  AI_OUTPUT="$REVIEW_OUTPUT"
  ai_classify
  ai_critique_loop
}

# --- the second opinion -------------------------------------------------------
#
# The reviewer already critiques its own drafts before emitting them. That pass
# is necessary and not sufficient: a model arguing against a conclusion it just
# reached shares all the reasoning that produced it, and agrees with itself far
# more readily than a stranger would. Hallucinated findings survive self-review
# precisely because the same reasoning generated and then blessed them.
#
# So the findings go to a different model, with two jobs and no others:
#
#   1. check the findings   - is each one real, in scope, unguarded, honestly
#                             severed? Drop and downgrade what is not.
#   2. report misdeclarations - findings that are wrongly *stated* rather than
#                             simply wrong: cited at the wrong line, filed under
#                             the wrong severity or category, resting on a
#                             mechanism never demonstrated, or duplicated.
#
# The critic does not rewrite them. It hands the misdeclarations back and the
# original reviewer corrects its own report, because a critic that edits
# findings has quietly become a second reviewer whose output nobody checked.
#
# Bounded at ai.critiqueRounds, because each round is two more model runs and
# the loop must terminate whether or not the two agents ever agree.
ai_critique_loop() {
  local round=0 log corrections

  [ -n "${INHOUSECODE_AI_CRITIQUE_MODEL:-}" ] || return 0
  [ "${INHOUSECODE_AI_CRITIQUE_ROUNDS:-0}" -gt 0 ] || return 0
  # Nothing to argue about, and nothing that could be hallucinated.
  [ "$(count_findings "$AI_OUTPUT" "$AI_FINDING_MARKER")" -gt 0 ] || return 0
  # A gate that produced no valid report has nothing worth a second opinion,
  # and must stay unavailable rather than be laundered into a verdict.
  [ "$AI_STATUS" = "unavailable" ] && return 0

  while [ "$round" -lt "$INHOUSECODE_AI_CRITIQUE_ROUNDS" ]; do
    round=$((round + 1))
    log="$INHOUSECODE_CACHE_ROOT/ai-critique-$AI_FIX_ROUNDS-$round.log"
    info "Second opinion: round $round/$INHOUSECODE_AI_CRITIQUE_ROUNDS with ${INHOUSECODE_AI_CRITIQUE_MODEL} (log: $log)"
    run_critique_agent "$(ai_critique_prompt)" "$log"

    ai_accept_critique "$round" || return 0

    corrections="$(count_marker_lines "$CRITIQUE_OUTPUT" "$AI_MISDECL_MARKER" 5)"
    if [ "${corrections:-0}" -eq 0 ]; then
      info "Second opinion: no misdeclarations; the report stands as critiqued."
      return 0
    fi

    print_misdeclarations "$CRITIQUE_OUTPUT" "$round"
    [ "$round" -ge "$INHOUSECODE_AI_CRITIQUE_ROUNDS" ] && {
      warn "inhousecode: reached the second-opinion budget with $corrections correction(s) outstanding."
      warn "  The critiqued report stands; the outstanding corrections are listed above."
      return 0
    }

    # Hand the corrections back to the author of the findings.
    log="$INHOUSECODE_CACHE_ROOT/ai-revision-$AI_FIX_ROUNDS-$round.log"
    info "Revising the report against $corrections correction(s) (log: $log)"
    run_review_agent "$(ai_revision_prompt "$CRITIQUE_OUTPUT")" "$log"
    ai_accept_revision || return 0
  done
  return 0
}

# The critic's report replaces the reviewer's, but only if it is well formed.
#
# A malformed critique keeps the findings it was asked to judge. That is the
# safe direction and the only honest one: the critique can subtract, so losing
# it can only leave MORE findings standing, never fewer. Treating it as a gate
# failure would block on the failure of a pass whose entire job is to unblock
# things that were never real.
ai_accept_critique() {
  local round="$1" merged
  if [ "$CRITIQUE_RC" -ne 0 ]; then
    warn "inhousecode: the second opinion exited with status $CRITIQUE_RC; keeping the original findings."
    return 1
  fi
  if ! validate_gate_output "$CRITIQUE_OUTPUT" "$AI_FINDING_MARKER" "$AI_VERDICT_PREFIX"; then
    warn "inhousecode: the second opinion was malformed; keeping the original findings."
    return 1
  fi

  merged="$(ai_merge_claims "$CRITIQUE_OUTPUT")" || return 1
  AI_OUTPUT="$merged"
  ai_classify "$CRITIQUE_RC"
  [ "$AI_STATUS" = "unavailable" ] && {
    warn "inhousecode: the second opinion produced no valid verdict; keeping the original findings."
    return 1
  }
  return 0
}

ai_accept_revision() {
  local merged
  if [ "$REVIEW_RC" -ne 0 ] ||
     ! validate_gate_output "$REVIEW_OUTPUT" "$AI_FINDING_MARKER" "$AI_VERDICT_PREFIX"; then
    warn "inhousecode: the revision failed; keeping the critiqued report."
    return 1
  fi
  merged="$(ai_merge_claims "$REVIEW_OUTPUT")" || return 1
  AI_OUTPUT="$merged"
  ai_classify "$REVIEW_RC"
  [ "$AI_STATUS" = "unavailable" ] && {
    warn "inhousecode: the revision produced no valid verdict; keeping the critiqued report."
    return 1
  }
  return 0
}

# Carry the intent checklist across a round in bash rather than asking either
# agent to reproduce it. The critique is about findings; a claim table that
# quietly loses rows every time a critic passes over it would be a report that
# gets less true the harder it is checked.
#
# The verdict must remain the last non-empty line, so the claim lines are spliced
# in ahead of it.
ai_merge_claims() {
  local content="$1" claims verdict body
  claims="$(lines_with_marker "$AI_OUTPUT" "$AI_CLAIM_MARKER" 4)"
  [ -n "$claims" ] || { printf '%s\n' "$content"; return 0; }

  # Anything the new report already carries wins; only genuinely absent rows
  # are restored, so a critic is still free to correct the checklist.
  [ -n "$(lines_with_marker "$content" "$AI_CLAIM_MARKER" 4)" ] && {
    printf '%s\n' "$content"
    return 0
  }
  verdict="$(gate_verdict "$content")"
  # Everything except the trailing verdict line.
  body="$(printf '%s\n' "$content" | awk '
    { lines[NR]=$0 }
    END {
      last=0
      for (i=1; i<=NR; i++) if (lines[i] ~ /[^ \t]/) last=i
      for (i=1; i<=NR; i++) if (i!=last) print lines[i]
    }')"
  printf '%s\n%s\n%s\n' "$body" "$claims" "$verdict"
}

ai_fix_round() {
  local selection="$1" heading="$2" work_order files log
  work_order="$(findings_as_work_order "$AI_OUTPUT" \
    "$AI_FINDING_MARKER" "$selection" "review")"
  [ -n "$work_order" ] || return 1
  files="$(cat "$INHOUSECODE_CACHE_ROOT/scan-files.txt" 2>/dev/null)"
  log="$INHOUSECODE_CACHE_ROOT/ai-fix-$AI_FIX_ROUNDS.log"
  run_fix_agent "$(fix_agent_prompt "$heading" "$work_order" "$files")" "$log" "repair"
  [ "$FIX_RC" -eq 0 ]
}

# Repair only what blocks, then re-review to confirm the repair actually landed.
ai_autofix_blocking() {
  local blocking
  while :; do
    blocking="$(count_findings "$AI_OUTPUT" "$AI_FINDING_MARKER" blocking)"
    [ "$blocking" -eq 0 ] && break
    [ "$INHOUSECODE_AI_AUTOFIX_BLOCKING" = "1" ] || break
    [ "$AI_FIX_ROUNDS" -ge "$INHOUSECODE_AI_MAX_FIX_LOOPS" ] && {
      warn "inhousecode: reached the review repair budget with $blocking blocking finding(s) left."
      break
    }
    AI_FIX_ROUNDS=$((AI_FIX_ROUNDS + 1))
    info "Review repair round $AI_FIX_ROUNDS/$INHOUSECODE_AI_MAX_FIX_LOOPS - $blocking blocking finding(s)."
    ai_fix_round blocking \
      "Resolve these blocking code-review findings in the repository at $REPO_ROOT." || break
    [ "$TARGET_MODE" = "staged" ] && static_restage
    ai_write_inputs || break
    ai_review_once
    print_claims_report "$AI_OUTPUT"
    print_findings_report "AI review (after repair round $AI_FIX_ROUNDS)" \
      "$AI_OUTPUT" "$AI_FINDING_MARKER" "$AI_VERDICT_PREFIX"
    [ "$AI_STATUS" = "unavailable" ] && break
  done
}

# Every finding is the developer's call, blocking or not. The report above
# already lists them all, numbered, with severity -- so this prompts against
# that one table rather than reprinting a subset. There is deliberately no
# separate advisory round: splitting the list meant the numbers on screen no
# longer matched the numbers you could type, and it stopped you fixing the
# findings that actually mattered.
#
# Recurses after applying fixes, because fixing begets findings and stopping at
# a report the developer cannot act on is the frustrating part. Bounded by
# ai.maxFixLoops.
ai_triage_findings() {
  local total answer chosen work_order files log prompt choices
  local all_indices blocking_indices example
  total="$(count_findings "$AI_OUTPUT" "$AI_FINDING_MARKER")"
  [ "$total" -gt 0 ] || return 0
  [ "$INHOUSECODE_AI_TRIAGE_FINDINGS" = "1" ] || return 0
  has_tty || {
    info "$total finding(s) reported; run 'inhousecode review' in a terminal to fix them."
    return 0
  }

  all_indices="$(finding_indices "$AI_OUTPUT" "$AI_FINDING_MARKER" all)"
  blocking_indices="$(finding_indices "$AI_OUTPUT" "$AI_FINDING_MARKER" blocking)"
  example="$(printf '%s' "$all_indices" | awk '{ print ($2!="" ? $1 "," $2 : $1) }')"

  step "Your call"
  if [ -n "$blocking_indices" ]; then
    say "  $total finding(s) above. ${C_RED}Blocking: $blocking_indices${C_RESET} - these must go before the commit passes."
  else
    say "  $total finding(s) above, none blocking."
  fi

  if [ "${INHOUSECODE_EXPLAIN_ENABLED:-0}" = "1" ]; then
    prompt=$'\n  Fix which? numbers like '"$example"$'  |  [a] all  |  [e] explain them  |  [n] none\n  > '
    choices="Pick from: $all_indices   (or a, e, n)"
  else
    prompt=$'\n  Fix which? numbers like '"$example"$'  |  [a] all  |  [n] none\n  > '
    choices="Pick from: $all_indices   (or a, n)"
  fi

  while :; do
    ask answer "$prompt"
    case "$answer" in
      n|N|"") return 0 ;;
      a|A) chosen="$(printf '%s' "$all_indices" | tr ' ' '\n')" ;;
      e|E)
        [ "${INHOUSECODE_EXPLAIN_ENABLED:-0}" = "1" ] || {
          printf '  %s\n' "$choices" > /dev/tty
          continue
        }
        # The session takes over from here; it can fix what the developer asks
        # for, so the numbered picker has nothing left to do.
        explain_handoff
        return 0
        ;;
      *)
        if ! chosen="$(parse_selection "$answer" "$all_indices")" || [ -z "$chosen" ]; then
          printf '  %s\n' "$choices" > /dev/tty
          continue
        fi
        ;;
    esac
    break
  done

  work_order="$(select_findings "$AI_OUTPUT" "$AI_FINDING_MARKER" all |
    awk -F'\t' -v picks="$(printf '%s' "$chosen" | tr '\n' ' ')" '
      BEGIN { split(picks, list, " "); for (i in list) wanted[list[i]+0]=1 }
      { n++ } n in wanted {
        printf "- [review][%s] %s | %s | Suggested fix: %s\n", $2, $3, $4, $5
      }')"
  [ -n "$work_order" ] || return 0

  files="$(cat "$INHOUSECODE_CACHE_ROOT/scan-files.txt" 2>/dev/null)"
  log="$INHOUSECODE_CACHE_ROOT/ai-picked-fix.log"
  info "Applying $(printf '%s\n' "$chosen" | grep -c .) selected fix(es)..."
  run_fix_agent "$(fix_agent_prompt \
    "Apply only the code-review findings the developer selected, in the repository at $REPO_ROOT." \
    "$work_order" "$files")" "$log" "picked fixes"
  [ "$TARGET_MODE" = "staged" ] && static_restage

  # Always re-review, whatever was picked -- one round, never a loop.
  #
  # This is not politeness, it is the verdict being true. A fix edits the tree
  # (and in staged mode restages it), so without this the run reports on code
  # that no longer exists: BLOCKED right after you cleared the blocker, or worse
  # PASS on edits no gate ever saw, which is exactly what invariant 8 forbids
  # for explain sessions. Skipping it saves nothing either -- the only way to
  # learn the truth would be re-running, and that costs both phases instead of
  # one review.
  ai_write_inputs || return 0
  ai_review_once
  print_claims_report "$AI_OUTPUT"
  print_findings_report "AI review (after your fixes)" "$AI_OUTPUT" \
    "$AI_FINDING_MARKER" "$AI_VERDICT_PREFIX"

  # Fixing begets findings. Rather than stopping at a fresh report the developer
  # cannot act on, offer the new list once more -- bounded by
  # ai.maxFixLoops so an unlucky pair of fixes cannot trap anyone in a cycle.
  if [ "$AI_STATUS" != "unavailable" ] &&
     [ "$AI_PICK_ROUNDS" -lt "$INHOUSECODE_AI_MAX_FIX_LOOPS" ]; then
    AI_PICK_ROUNDS=$((AI_PICK_ROUNDS + 1))
    ai_triage_findings
  elif [ "$AI_PICK_ROUNDS" -ge "$INHOUSECODE_AI_MAX_FIX_LOOPS" ] &&
       [ "$(count_findings "$AI_OUTPUT" "$AI_FINDING_MARKER")" -gt 0 ]; then
    warn "inhousecode: reached the triage budget ($INHOUSECODE_AI_MAX_FIX_LOOPS rounds)."
    info "inhousecode: run it again to keep working through what is left."
  fi
  return 0
}

run_ai_gate() {
  if [ "$INHOUSECODE_AI_ENABLED" != "1" ]; then
    AI_STATUS="skipped"
    return 0
  fi
  step "Phase 2/2 - AI code review"
  ensure_copilot || { AI_STATUS="unavailable"; AI_ERROR="Copilot CLI is unavailable"; return 1; }
  ai_write_inputs || { AI_STATUS="unavailable"; return 1; }

  ai_review_once
  print_claims_report "$AI_OUTPUT"
  print_findings_report "AI review" "$AI_OUTPUT" \
    "$AI_FINDING_MARKER" "$AI_VERDICT_PREFIX"
  [ "$AI_STATUS" = "unavailable" ] && return 1

  ai_autofix_blocking
  ai_triage_findings
  return 0
}
