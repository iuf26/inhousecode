#!/usr/bin/env bash
#
# Phase 1 — the deterministic gate.
#
# Semgrep runs first, before any model sees the change, so that objectively
# detectable vulnerabilities are caught by a tool with no opinions and no
# variance. The gate then drives a bounded repair loop: hand the findings to a
# fixer agent, re-scan, and repeat until the scan is clean, the loop stops making
# progress, or the iteration budget runs out.
#
# Exports: STATIC_STATUS (pass|fail|unavailable|skipped), STATIC_OUTPUT,
#          STATIC_ERROR, STATIC_FIX_ROUNDS

STATIC_STATUS="not-run"
STATIC_OUTPUT=""
STATIC_ERROR=""
STATIC_FIX_ROUNDS=0

static_scan_once() {
  local envelope="$INHOUSECODE_CACHE_ROOT/scan-envelope.json"
  if ! INHOUSECODE_TARGET_MODE="$TARGET_MODE" \
       INHOUSECODE_TARGET_PATH="$TARGET_PATH" \
       INHOUSECODE_DIFF_BASE="${DIFF_MERGE_BASE:-}" \
       INHOUSECODE_DIFF_HEAD="${DIFF_HEAD:-HEAD}" \
       INHOUSECODE_DIFF_SOURCE="${DIFF_SOURCE:-commit}" \
       INHOUSECODE_SEMGREP_CONFIGS="$INHOUSECODE_STATIC_SEMGREP_CONFIGS" \
       INHOUSECODE_CACHE_ROOT="$INHOUSECODE_CACHE_ROOT" \
       bash "$INHOUSECODE_HOME/lib/static_scan.sh" > "$envelope"; then
    STATIC_ERROR="the Semgrep scan command failed"
    return 1
  fi
  local raw rc
  raw="$(INHOUSECODE_CACHE_ROOT="$INHOUSECODE_CACHE_ROOT" \
    "${PYTHON_CMD[@]}" "$INHOUSECODE_HOME/lib/static_report.py" "$envelope")"
  rc=$?
  STATIC_OUTPUT="$(strip_cr "$raw")"
  STATIC_REPORT_RC=$rc
  return 0
}

static_classify() {
  local verdict blocking
  verdict="$(gate_verdict "$STATIC_OUTPUT")"
  blocking="$(count_findings "$STATIC_OUTPUT" "$STATIC_FINDING_MARKER" blocking)"

  if ! validate_gate_output "$STATIC_OUTPUT" \
      "$STATIC_FINDING_MARKER" "$STATIC_VERDICT_PREFIX"; then
    STATIC_STATUS="unavailable"
    STATIC_ERROR="the static gate emitted a malformed report"
    return
  fi
  if [ "$STATIC_REPORT_RC" -eq 0 ] && [ "$verdict" = "$STATIC_VERDICT_PREFIX: PASS" ]; then
    STATIC_STATUS="pass"
  elif [ "$STATIC_REPORT_RC" -eq 1 ] && [ "$verdict" = "$STATIC_VERDICT_PREFIX: FAIL" ] &&
      [ "$blocking" -gt 0 ]; then
    STATIC_STATUS="fail"
  else
    STATIC_STATUS="unavailable"
    STATIC_ERROR="${STATIC_ERROR:-the static scan could not complete}"
  fi
}

# Re-stage the files that were already staged so the next scan sees the repairs.
# Only previously staged paths are touched; the loop never adds new files to the
# commit on the developer's behalf.
static_restage() {
  local list="$INHOUSECODE_CACHE_ROOT/staged-paths.txt" path
  [ "$TARGET_MODE" = "staged" ] || return 0
  [ "$INHOUSECODE_STATIC_RESTAGE_FIXES" = "1" ] || {
    warn "inhousecode: fixes are not re-staged (static.restageFixes is false); stage them yourself and re-run."
    return 1
  }
  [ -s "$list" ] || return 0
  while IFS= read -r path; do
    [ -n "$path" ] && [ -e "$path" ] && git add -- "$path"
  done < "$list"
}

static_fix_round() {
  local selection="$1" work_order files prompt log
  work_order="$(findings_as_work_order "$STATIC_OUTPUT" \
    "$STATIC_FINDING_MARKER" "$selection" "semgrep")"
  [ -n "$work_order" ] || return 1
  files="$(cat "$INHOUSECODE_CACHE_ROOT/scan-files.txt" 2>/dev/null)"
  log="$INHOUSECODE_CACHE_ROOT/static-fix-$STATIC_FIX_ROUNDS.log"

  prompt="$(fix_agent_prompt \
    "Resolve these Semgrep static-analysis findings in the repository at $REPO_ROOT." \
    "$work_order" "$files")"
  run_fix_agent "$prompt" "$log" "semgrep repair"
  [ "$FIX_RC" -eq 0 ]
}

run_static_gate() {
  if [ "$INHOUSECODE_STATIC_ENABLED" != "1" ]; then
    STATIC_STATUS="skipped"
    return 0
  fi

  local selection="$INHOUSECODE_STATIC_FIX_SEVERITY" remaining previous_remaining=-1
  case "$selection" in
    all|blocking) ;;
    *) selection="all" ;;
  esac

  step "Phase 1/2 - static analysis (Semgrep)"
  while :; do
    if ! static_scan_once; then
      STATIC_STATUS="unavailable"
      return 1
    fi
    cp -f "$INHOUSECODE_CACHE_ROOT/scan-envelope.json" \
      "$INHOUSECODE_CACHE_ROOT/scan-envelope.last.json" 2>/dev/null || true
    static_classify
    print_findings_report "Static analysis" "$STATIC_OUTPUT" \
      "$STATIC_FINDING_MARKER" "$STATIC_VERDICT_PREFIX"

    [ "$STATIC_STATUS" = "unavailable" ] && return 1
    remaining="$(count_findings "$STATIC_OUTPUT" "$STATIC_FINDING_MARKER" "$selection")"
    [ "$remaining" -eq 0 ] && break

    if [ "$INHOUSECODE_STATIC_AUTOFIX" != "1" ]; then
      warn "inhousecode: automatic repair is disabled (static.autofix is false)."
      break
    fi
    if [ "$STATIC_FIX_ROUNDS" -ge "$INHOUSECODE_STATIC_MAX_FIX_LOOPS" ]; then
      warn "inhousecode: reached the static repair budget of $INHOUSECODE_STATIC_MAX_FIX_LOOPS round(s) with $remaining finding(s) left."
      break
    fi
    # A round that removes nothing will not start removing anything on the next
    # attempt either; stop instead of burning the whole budget.
    if [ "$previous_remaining" -ne -1 ] && [ "$remaining" -ge "$previous_remaining" ]; then
      warn "inhousecode: the last repair round made no progress ($remaining finding(s) left); stopping the loop."
      break
    fi
    previous_remaining="$remaining"

    STATIC_FIX_ROUNDS=$((STATIC_FIX_ROUNDS + 1))
    info "Static repair round $STATIC_FIX_ROUNDS/$INHOUSECODE_STATIC_MAX_FIX_LOOPS - $remaining finding(s) to resolve."
    if ! static_fix_round "$selection"; then
      warn "inhousecode: the static repair round did not complete."
      break
    fi
    static_restage || break
  done

  [ "$STATIC_FIX_ROUNDS" -gt 0 ] &&
    info "Static analysis: $STATIC_FIX_ROUNDS repair round(s) applied."
  return 0
}
