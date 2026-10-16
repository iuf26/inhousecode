#!/usr/bin/env bash
# Resolve the repository default and per-run fix flags into one repair policy.

fix_policy_apply() {
  INHOUSECODE_FIX_ALL=0

  # An explicit report-only request always wins, even when --fix was also
  # supplied or the repository opted into automatic repairs.
  if [ "${NO_FIX:-0}" = "1" ]; then
    INHOUSECODE_STATIC_AUTOFIX=0
    INHOUSECODE_AI_AUTOFIX_BLOCKING=0
    INHOUSECODE_AI_TRIAGE_FINDINGS=0
    export INHOUSECODE_FIX_ALL INHOUSECODE_STATIC_AUTOFIX
    export INHOUSECODE_AI_AUTOFIX_BLOCKING INHOUSECODE_AI_TRIAGE_FINDINGS
    return 0
  fi

  if [ "${FIX_REQUESTED:-0}" = "1" ] ||
     [ "${INHOUSECODE_REVIEW_FIX_BY_DEFAULT:-0}" = "1" ]; then
    FIX_REQUESTED=1
    INHOUSECODE_FIX_ALL=1
    INHOUSECODE_STATIC_AUTOFIX=1
    INHOUSECODE_AI_AUTOFIX_BLOCKING=1
    # Automatic all-finding repair replaces the interactive picker.
    INHOUSECODE_AI_TRIAGE_FINDINGS=0
  fi

  export FIX_REQUESTED INHOUSECODE_FIX_ALL INHOUSECODE_STATIC_AUTOFIX
  export INHOUSECODE_AI_AUTOFIX_BLOCKING INHOUSECODE_AI_TRIAGE_FINDINGS
}