#!/usr/bin/env bash
#
# Adversarial review driver.
#
# The heavy, opt-in counterpart to the single-pass AI gate. Where the fast gate
# runs one subtractive reviewer, this spawns several adversarial LENSES in
# parallel -- each a separate reviewer on the configured adversarial model,
# attacking the change from one angle -- then runs one SUBTRACTIVE synthesis pass
# that merges, deduplicates, applies a lead judgment, and emits the final report.
#
# Two postures, deliberately opposite (see skills/adversarial-review/SKILL.md):
#   - lenses are ADDITIVE: surface every real problem from their angle.
#   - synthesis is SUBTRACTIVE: it may drop or downgrade, never invent or raise.
#
# The synthesis output is the standard finding+verdict contract, so ai_classify,
# print_findings_report, and the repair loop all consume it unchanged. This file
# reuses ai_output_contract / ai_build_prompt inputs from gate_ai.sh.

ADVERSARIAL_LENSES=""

# Size the change and choose lenses. Small: Skeptic. Medium: +Architect.
# Large: +Minimalist. Operationally sensitive changes add Operator regardless
# of size. Capped by adversarial.maxLenses. The Skeptic always runs.
adversarial_size_lenses() {
  local files=0 lines=0
  [ -f "$INHOUSECODE_CACHE_ROOT/scan-files.txt" ] &&
    files="$(grep -c . "$INHOUSECODE_CACHE_ROOT/scan-files.txt" 2>/dev/null || echo 0)"
  [ -n "${AI_DIFF_PATH:-}" ] && [ -f "$AI_DIFF_PATH" ] &&
    lines="$(grep -cE '^[+-]' "$AI_DIFF_PATH" 2>/dev/null || echo 0)"

  # Size alone is a poor proxy for operational risk. A one-line timeout,
  # migration, deployment, or retry change can matter more than a large local
  # refactor, so select Operator from the changed paths and diff semantics too.
  local operational=0
  if grep -qiE '(^|/)(Dockerfile|docker-compose|compose\.ya?ml|Makefile|Procfile|.*\.service|.*\.socket|k8s|kubernetes|helm|terraform|ansible|deploy|deployment|migration|migrations|schema|queue|worker|job|cron|health|readiness|liveness|metrics|monitoring|observability|runbook)(/|\.|$)' \
      "$INHOUSECODE_CACHE_ROOT/scan-files.txt" 2>/dev/null; then
    operational=1
  fi
  if [ "$operational" = "0" ] && [ -n "${AI_DIFF_PATH:-}" ] && [ -f "$AI_DIFF_PATH" ] &&
      grep -qiE 'timeout|retry|backoff|circuit.?breaker|transaction|rollback|migration|queue|worker|cron|lock|concurr|cache|rate.?limit|health.?check|readiness|liveness|metric|alert|log|deploy|rollback|feature.?flag|resource|memory|disk|network|http|database|connection.?pool|batch|pagination' \
        "$AI_DIFF_PATH" 2>/dev/null; then
    operational=1
  fi

  local want=1
  if [ "$files" -ge 5 ] || [ "$lines" -ge 200 ]; then
    want=3
  elif [ "$files" -ge 3 ] || [ "$lines" -ge 50 ]; then
    want=2
  fi

  local cap="${INHOUSECODE_ADVERSARIAL_MAX_LENSES:-4}"

  if [ "$operational" = "1" ]; then
    # Operator is higher priority than Minimalist when the cap forces a choice.
    if [ "$cap" -le 1 ]; then
      ADVERSARIAL_LENSES="skeptic"
    elif [ "$want" -le 1 ] || [ "$cap" -eq 2 ]; then
      ADVERSARIAL_LENSES="skeptic operator"
    elif [ "$want" -eq 2 ] || [ "$cap" -eq 3 ]; then
      ADVERSARIAL_LENSES="skeptic architect operator"
    else
      ADVERSARIAL_LENSES="skeptic architect minimalist operator"
    fi
  else
    [ "$want" -gt "$cap" ] && want="$cap"
    case "$want" in
      1) ADVERSARIAL_LENSES="skeptic" ;;
      2) ADVERSARIAL_LENSES="skeptic architect" ;;
      *) ADVERSARIAL_LENSES="skeptic architect minimalist" ;;
    esac
  fi
}

# One lens's prompt. Additive posture: attack from this lens, surface everything
# real, emit the finding contract -- but NO verdict line (the synthesis owns the
# verdict). The lens still must cite file:line and a mechanism per finding.
adversarial_lens_prompt() {
  local lens="$1"
  local skill="$INHOUSECODE_HOME/skills/adversarial-review/SKILL.md"
  local lenses_ref="$INHOUSECODE_HOME/skills/adversarial-review/references/reviewer-lenses.md"
  local principles="$INHOUSECODE_HOME/skills/adversarial-review/references/principles"
  local memory_line=""
  command -v memory_prompt_block >/dev/null 2>&1 &&
    memory_line="
$(memory_prompt_block)"

  local source_line="Review source: the change described by the diff below."
  local context_line="Repository context: before judging this lens, read the relevant README, architecture, deployment, configuration, runbook, and service documentation in the repository. Use those documents to understand what runs in production; do not assume an operational property that the repository does not establish."
  local inputs="- In-scope files (read this file for the list): $INHOUSECODE_CACHE_ROOT/scan-files.txt
- Repository root: ${AI_SOURCE_ROOT:-$REPO_ROOT}"
  if [ "$TARGET_MODE" = "path" ]; then
    source_line="Review source: path review of '$TARGET_PATH'. Review the full contents of every in-scope file."
  else
    inputs="- Diff: $AI_DIFF_PATH
$inputs"
    [ -n "${AI_INTENT_PATH:-}" ] && inputs="$inputs
- Intent brief (what this change is supposed to deliver): $AI_INTENT_PATH"
  fi

  printf '%s\n' \
    "You are an ADVERSARIAL code reviewer running as an automated gate. You are" \
    "assigned exactly ONE lens: the ${lens} lens. Adopt it exclusively -- do not" \
    "try to be balanced. Your job is to find REAL problems from this angle, not" \
    "to validate the work." \
    "" \
    "Read, in this order:" \
    "- Your method: $skill" \
    "- Your lens definition (use ONLY the '${lens}' section): $lenses_ref" \
    "- The engineering principles your findings map to (read the files your lens maps to in this folder): $principles/" \
    "$memory_line" \
    "" \
    "$source_line" \
    "$context_line" \
    "Read only these inputs:" \
    "$inputs" \
    "" \
    "Judge only the changed lines and their direct consequences. Cite a real" \
    "file:line and a concrete failure scenario for every finding. Do NOT invent" \
    "problems to fill a quota: if this lens finds nothing real, emit no finding" \
    "lines and say so in one sentence." \
    "" \
    "OUTPUT CONTRACT - NOT OPTIONAL" \
    "Emit one line per finding, with real TAB characters between five fields:" \
    "" \
    "${AI_FINDING_MARKER}<TAB>SEVERITY<TAB>file:line<TAB>category<TAB>one-line fix" \
    "" \
    "  SEVERITY   exactly one of CRITICAL, HIGH, MEDIUM, LOW" \
    "  file:line  repository-relative path and the line number" \
    "  category   two or three words (kebab-case), or the stable approved memory record id" \
    "  fix        one imperative sentence, on a single line" \
    "" \
    "Do NOT emit a verdict line -- the synthesis pass owns the verdict. Do not" \
    "wrap lines in code fences, quotes, or bullets. Do not run shell commands," \
    "modify files, or ask questions."
}

# The synthesis + lead-judgment prompt. Subtractive posture. It is handed every
# lens's raw findings and must merge, deduplicate, drop/downgrade what it can
# disprove, and emit the standard contract + verdict. It may not invent findings
# or raise a severity beyond what a lens reported.
adversarial_synthesis_prompt() {
  local findings_file="$1"
  local verdict_ref="$INHOUSECODE_HOME/skills/adversarial-review/references/verdict-format.md"
  local memory_line=""
  command -v memory_prompt_block >/dev/null 2>&1 && memory_line="$(memory_prompt_block)"

  printf '%s\n' \
    "You are the LEAD reviewer synthesizing an adversarial review. Several" \
    "adversarial lenses each reviewed the same change and produced the findings" \
    "below. The lenses are adversarial by design and overreach; your job is to" \
    "produce the final, trustworthy report." \
    "" \
    "$memory_line" \
    "Verdict format and rules: $verdict_ref" \
    "" \
    "The lenses' raw findings (already in contract shape): $findings_file" \
    "" \
    "Do exactly this:" \
    "1. Merge and DEDUPLICATE: the same defect raised by two lenses is one" \
    "   finding. Keep the highest justified severity among duplicates." \
    "2. For each finding, apply a LEAD JUDGMENT: keep it only if it names a real" \
    "   line and a concrete mechanism, is introduced by this change, and no" \
    "   existing guard makes it moot. Drop or downgrade what fails this test." \
    "3. You may ONLY subtract: drop a finding or lower its severity. You may NOT" \
    "   invent a new finding or raise a severity beyond what a lens reported -- a" \
    "   finding no lens raised would reach the developer critiqued by nobody." \
    "   Drop only what you can disprove; a finding you cannot check stays." \
    "" \
    "OUTPUT CONTRACT - NOT OPTIONAL" \
    "Emit one line per surviving finding, with real TAB characters:" \
    "" \
    "${AI_FINDING_MARKER}<TAB>SEVERITY<TAB>file:line<TAB>category<TAB>one-line fix" \
    "" \
    "Then, as the LAST non-empty line of your response, print exactly one of:" \
    "" \
    "${AI_VERDICT_PREFIX}: FAIL     (if at least one surviving CRITICAL or HIGH finding)" \
    "${AI_VERDICT_PREFIX}: PASS     (only if there are none)" \
    "" \
    "Every finding must appear as a ${AI_FINDING_MARKER} line; prose does not" \
    "count. Never print PASS while a CRITICAL or HIGH line exists. Emit the" \
    "verdict even when nothing survives. No code fences, no shell, no questions."
}

# Orchestrate: size, spawn lenses in parallel, collect, synthesize. Sets
# AI_OUTPUT and AI_STATUS via ai_classify, exactly like ai_review_once, so the
# rest of the gate is unchanged.
run_adversarial_review() {
  adversarial_size_lenses
  local n; n="$(printf '%s\n' $ADVERSARIAL_LENSES | grep -c .)"
  local model_note="the primary review model"
  [ -n "${INHOUSECODE_ADVERSARIAL_MODEL:-}" ] && model_note="model '$INHOUSECODE_ADVERSARIAL_MODEL'"
  info "Adversarial review: $n lens(es) [$ADVERSARIAL_LENSES] on $model_note"

  local lens log pids="" any=0
  local combined="$INHOUSECODE_CACHE_ROOT/adversarial-findings.txt"
  : > "$combined"

  # Spawn each lens in the background, each writing its own log.
  for lens in $ADVERSARIAL_LENSES; do
    log="$INHOUSECODE_CACHE_ROOT/adversarial-$lens.log"
    adversarial_lens_worker "$lens" "$log" &
    pids="$pids $!"
  done
  # Wait for all lenses; a failed lens is noted, not fatal (a review must not
  # collapse because one of several reviewers errored).
  wait $pids 2>/dev/null || true

  for lens in $ADVERSARIAL_LENSES; do
    log="$INHOUSECODE_CACHE_ROOT/adversarial-$lens.log"
    local out; out="$(strip_cr "$(agent_text "$log" 2>/dev/null)")"
    usage_record "adversarial:$lens" "$log"
    if [ -n "$out" ]; then
      printf '# lens: %s\n%s\n' "$lens" "$out" >> "$combined"
      case "$out" in
        *"$AI_FINDING_MARKER"*) any=1 ;;
      esac
    else
      warn "inhousecode: the $lens lens produced no output (log: $log)"
      printf '# lens: %s (no output)\n' "$lens" >> "$combined"
    fi
  done

  # Synthesis pass: subtractive merge + verdict, on the primary review model
  # (the lead judgment is a judging role, not an attacking one).
  local synth_log="$INHOUSECODE_CACHE_ROOT/adversarial-synthesis.log"
  info "Adversarial review: synthesizing verdict"
  run_review_agent "$(adversarial_synthesis_prompt "$combined")" "$synth_log"
  AI_OUTPUT="$REVIEW_OUTPUT"
  ai_classify

  # If the synthesis itself failed to produce a valid verdict but lenses did
  # find things, surface that as unavailable rather than a false pass.
  if [ "$AI_STATUS" = "unavailable" ] && [ "$any" = "1" ]; then
    AI_ERROR="the adversarial synthesis produced no valid verdict"
  fi
}

# A single lens worker, run in the background. Kept as a function so the spawn
# loop stays readable and the prompt build happens in the child.
adversarial_lens_worker() {
  local lens="$1" log="$2"
  local model="${INHOUSECODE_ADVERSARIAL_MODEL:-}"
  [ -n "$model" ] || model="${INHOUSECODE_AI_MODEL:-}"
  harness_review_cmd "$(adversarial_lens_prompt "$lens")" "$log" \
    "$INHOUSECODE_AI_TIMEOUT_SEC" "$model" "${INHOUSECODE_VERBOSE:-0}"
}
