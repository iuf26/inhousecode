#!/usr/bin/env bash
#
# Shared helpers for every inhousecode gate: configuration loading, terminal
# reporting, and the finding-line contract that both gates emit.
#
# A finding line is a single tab-separated record:
#   <MARKER>\t<SEVERITY>\t<file:line>\t<category>\t<one-line fix>
# CRITICAL and HIGH are blocking; MEDIUM and LOW are advisory.

# --- named constants ---------------------------------------------------------
STATIC_FINDING_MARKER="##STATIC-FINDING##"
STATIC_VERDICT_PREFIX="STATIC-CHECK"
AI_FINDING_MARKER="##CR-FINDING##"
AI_VERDICT_PREFIX="CODE-REVIEW"
# The intent checklist: one line per claim the change's own description makes,
# with the reviewer's verdict on whether the code actually delivers it. It is
# reported separately from findings because a claim is not a defect -- an
# unmet one becomes a finding too, and that is what carries severity.
#   <MARKER>\t<STATUS>\t<claim>\t<evidence>
AI_CLAIM_MARKER="##CR-CLAIM##"
# A misdeclaration: the critic's report that a finding is not merely wrong but
# wrongly *stated* -- cited at the wrong line, filed under the wrong severity,
# or resting on a mechanism it never demonstrated. These go back to the reviewer
# to correct, which is the one thing a critic cannot do for it: rewriting
# another agent's finding is how a critic becomes a second reviewer whose own
# output nobody checked.
#   <MARKER>\t<ISSUE>\t<finding location>\t<what is wrong>\t<required correction>
AI_MISDECL_MARKER="##CR-MISDECL##"
TIMEOUT_EXIT_STATUS=124
# Minimum column widths keep the findings table readable when every value is short.
TABLE_MIN_COLUMN_WIDTH=8

# --- terminal ----------------------------------------------------------------

if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
  C_RESET=$'\033[0m'; C_BOLD=$'\033[1m'; C_DIM=$'\033[2m'
  C_RED=$'\033[31m'; C_GREEN=$'\033[32m'; C_YELLOW=$'\033[33m'; C_BLUE=$'\033[34m'
else
  C_RESET=""; C_BOLD=""; C_DIM=""; C_RED=""; C_GREEN=""; C_YELLOW=""; C_BLUE=""
fi

say()  { printf '%s\n' "$*"; }
info() { printf '%s\n' "${C_BLUE}${*}${C_RESET}"; }
good() { printf '%s\n' "${C_GREEN}${*}${C_RESET}"; }
warn() { printf '%s\n' "${C_YELLOW}${*}${C_RESET}" >&2; }
fail() { printf '%s\n' "${C_RED}${*}${C_RESET}" >&2; }
step() { printf '\n%s\n' "${C_BOLD}${*}${C_RESET}"; }

has_tty() { { tty -s </dev/tty; } 2>/dev/null; }

ask() {
  # ask <prompt-var-name> <prompt-text>; reads from the terminal, not stdin,
  # so it works inside a git hook whose stdin is closed.
  # Locals are underscore-prefixed so they never shadow the caller's variable
  # name; a collision would leave the caller's variable unset under `set -u`.
  local __ask_target="$1" __ask_prompt="$2" __ask_reply
  printf '%s' "$__ask_prompt" > /dev/tty
  IFS= read -r __ask_reply < /dev/tty || __ask_reply=""
  printf -v "$__ask_target" '%s' "$__ask_reply"
}

# --- environment -------------------------------------------------------------

resolve_python() {
  PYTHON_CMD=()
  if command -v python3 >/dev/null 2>&1 &&
      python3 -c 'import sys; raise SystemExit(sys.version_info.major != 3)' 2>/dev/null; then
    PYTHON_CMD=(python3)
  elif command -v python >/dev/null 2>&1 &&
      python -c 'import sys; raise SystemExit(sys.version_info.major != 3)' 2>/dev/null; then
    PYTHON_CMD=(python)
  elif command -v py >/dev/null 2>&1 && py -3 -c 'import sys' 2>/dev/null; then
    PYTHON_CMD=(py -3)
  else
    return 1
  fi
}

resolve_timeout() {
  TIMEOUT_BIN=""
  local candidate
  for candidate in timeout gtimeout; do
    if command -v "$candidate" >/dev/null 2>&1 &&
        "$candidate" 1 true >/dev/null 2>&1; then
      TIMEOUT_BIN="$candidate"
      return 0
    fi
  done
  return 1
}

# Locate the active harness CLI binary. Delegates to lib/harness.sh, which
# selects the adapter for INHOUSECODE_HARNESS (default: copilot) and resolves
# its binary. resolve_copilot() is kept as a backward-compatible alias.
#
# Not itself named resolve_harness_bin: lib/harness.sh defines a function of
# that exact name (the real public API, which loads the adapter first) and
# sourcing it from inside a same-named function here would redefine the
# function out from under its own still-running invocation.
resolve_harness() {
  # shellcheck source=harness.sh
  source "$INHOUSECODE_HOME/lib/harness.sh"
  resolve_harness_bin
}

resolve_copilot() { resolve_harness; }

# --- configuration -----------------------------------------------------------

load_config() {
  # Populates INHOUSECODE_* variables from the layered configuration documents.
  resolve_python || {
    fail "inhousecode: Python 3 is required."
    return 1
  }
  local rendered
  if ! rendered="$("${PYTHON_CMD[@]}" "$INHOUSECODE_HOME/lib/config.py" \
      "$INHOUSECODE_HOME" "$REPO_ROOT" | tr -d '\r')"; then
    return 1
  fi
  eval "$rendered"
}

# Windows toolchains (Python, and some Copilot builds) emit CRLF. The finding
# contract is line- and tab-delimited and is parsed with awk, so a stray CR
# silently corrupts the last field of every line. Normalize once, at capture.
strip_cr() { printf '%s' "$1" | tr -d '\r'; }

# --- findings ----------------------------------------------------------------

# De-duplicate on normalized location + category, keeping the highest severity
# and the original emission order.
unique_findings() {
  local content="$1" marker="$2"
  printf '%s\n' "$content" | awk -F'\t' -v marker="$marker" '
    function rank(severity) {
      return severity=="CRITICAL" ? 1 : severity=="HIGH" ? 2 : severity=="MEDIUM" ? 3 : 4
    }
    function normalize(value) {
      gsub(/^[[:space:]]+|[[:space:]]+$/, "", value); return tolower(value)
    }
    $1==marker && NF>=5 {
      key=normalize($3) SUBSEP normalize($4)
      current=rank($2)
      if (!(key in seen)) {
        seen[key]=++count; order[count]=key
        best[key]=current; line[key]=$0
      } else if (current < best[key]) {
        best[key]=current; line[key]=$0
      }
    }
    END { for (i=1; i<=count; i++) print line[order[i]] }'
}

# select: all | blocking
select_findings() {
  local content="$1" marker="$2" select="${3:-all}"
  unique_findings "$content" "$marker" | awk -F'\t' -v select="$select" '
    {
      blocking = ($2=="CRITICAL" || $2=="HIGH")
      if (select=="blocking" && !blocking) next
      print
    }'
}

count_findings() {
  select_findings "$1" "$2" "${3:-all}" | grep -c . 2>/dev/null || true
}

# One table per run, listing every finding, numbered once. The severity column
# is what separates blocking from advisory -- there is deliberately no second
# table. Rendering a subset separately meant the same finding appeared as #3 in
# one table and #1 in another on the same screen, so a developer who trusted the
# first one selected the wrong fix. The number you read here is the number you
# type at the prompt, and there is only one place to read it.
findings_table() {
  local content="$1" marker="$2"
  select_findings "$content" "$marker" all |
    awk -F'\t' -v min="$TABLE_MIN_COLUMN_WIDTH" '
    {
      n++
      severity[n]=$2; location[n]=$3; category[n]=$4; fix[n]=$5
      if (length($2)>sw) sw=length($2)
      if (length($3)>lw) lw=length($3)
      if (length($4)>cw) cw=length($4)
    }
    END {
      if (n==0) exit 1
      if (sw<min) sw=min
      if (lw<min) lw=min
      if (cw<min) cw=min
      printf "  %-3s  %-*s  %-*s  %-*s  %s\n", "#", sw,"SEVERITY", lw,"LOCATION", cw,"CATEGORY", "FIX"
      for (i=1;i<=n;i++)
        printf "  %-3d  %-*s  %-*s  %-*s  %s\n", i, sw,severity[i], lw,location[i], cw,category[i], fix[i]
    }'
}

# Which of the table's numbers belong to a subset, ascending, space-separated.
# This is the authoritative answer to "which numbers may the developer type?",
# and the only thing that needs to know about subsets now that there is one
# table. Numbering here must match findings_table: both walk `all` in order.
finding_indices() {
  local content="$1" marker="$2" select="${3:-all}"
  local blocking_only=0
  case "$select" in
    blocking) blocking_only=1 ;;
  esac
  select_findings "$content" "$marker" all |
    awk -F'\t' -v want_blocking="$blocking_only" '
      {
        n++
        blocking = ($2=="CRITICAL" || $2=="HIGH")
        if (want_blocking && !blocking) next
        out = out (out=="" ? "" : " ") n
      }
      END { print out }'
}

# Render findings as a work order for a fixer agent.
findings_as_work_order() {
  local content="$1" marker="$2" select="${3:-blocking}" label="$4"
  select_findings "$content" "$marker" "$select" |
    awk -F'\t' -v label="$label" '
      { printf "- [%s][%s] %s | %s | Suggested fix: %s\n", label, $2, $3, $4, $5 }'
}

# Every well-formed line carrying a marker, verbatim. Used to move the intent
# checklist across a critique round untouched: a critic judges findings, and
# has no business rewriting the claim table on its way past.
lines_with_marker() {
  local content="$1" marker="$2" fields="${3:-0}"
  printf '%s\n' "$content" | awk -F'\t' -v marker="$marker" -v want="$fields" '
    $1==marker && (want==0 || NF==want)'
}

count_marker_lines() {
  lines_with_marker "$1" "$2" "${3:-0}" | grep -c . 2>/dev/null || true
}

print_findings_report() {
  local heading="$1" content="$2" marker="$3" verdict_prefix="$4"
  local total blocking advisory
  total="$(count_findings "$content" "$marker")"
  blocking="$(count_findings "$content" "$marker" blocking)"
  advisory=$((total - blocking))

  step "=== $heading ==="
  if [ "$total" -eq 0 ]; then
    printf '%s\n' "$content" |
      grep -v "^${marker}" | grep -v "^${AI_CLAIM_MARKER}" |
      grep -v "^${AI_MISDECL_MARKER}" | grep -v "^${verdict_prefix}:" || true
    good "No findings."
    return 0
  fi
  say "Findings: $total total - ${C_RED}$blocking blocking${C_RESET}, $advisory advisory"
  say ""
  findings_table "$content" "$marker"
}

# The description said it would do these things. This is what it actually did.
#
# Rendered above the findings table and never numbered alongside it, because
# these are not selectable work items -- invariant 7 requires the numbers on
# screen to be the numbers the developer may type, and there is exactly one
# table that owns those. An UNMET claim the reviewer considers actionable
# arrives in the findings table on its own, carrying a severity.
print_claims_report() {
  local content="$1"
  local rendered
  rendered="$(printf '%s\n' "$content" |
    awk -F'\t' -v marker="$AI_CLAIM_MARKER" -v min="$TABLE_MIN_COLUMN_WIDTH" '
      $1==marker && NF==4 {
        n++
        status[n]=$2; claim[n]=$3; evidence[n]=$4
        if (length($2)>sw) sw=length($2)
        if (length($3)>cw) cw=length($3)
      }
      END {
        if (n==0) exit 1
        if (sw<min) sw=min
        if (cw<min) cw=min
        printf "  %-*s  %-*s  %s\n", sw,"STATUS", cw,"CLAIM", "EVIDENCE"
        for (i=1;i<=n;i++)
          printf "  %-*s  %-*s  %s\n", sw,status[i], cw,claim[i], evidence[i]
      }')" || return 0

  step "=== Stated intent vs. delivered ==="
  printf '%s\n' "$rendered"
  printf '%s\n' "$content" |
    awk -F'\t' -v marker="$AI_CLAIM_MARKER" '
      $1==marker && $2!="MET" { n++ }
      END { if (n>0) printf "\n  %d claim(s) are not fully delivered by this change.\n", n }'
}

# What the critic sent back for the reviewer to fix. Printed only when a round
# actually happened and found something, because a silent second opinion is
# indistinguishable from no second opinion at all.
print_misdeclarations() {
  local content="$1" round="$2"
  local rendered
  rendered="$(lines_with_marker "$content" "$AI_MISDECL_MARKER" 5 |
    awk -F'\t' -v min="$TABLE_MIN_COLUMN_WIDTH" '
      {
        n++
        issue[n]=$2; location[n]=$3; problem[n]=$4
        if (length($2)>iw) iw=length($2)
        if (length($3)>lw) lw=length($3)
      }
      END {
        if (n==0) exit 1
        if (iw<min) iw=min
        if (lw<min) lw=min
        printf "  %-*s  %-*s  %s\n", iw,"ISSUE", lw,"FINDING", "WHAT IS WRONG"
        for (i=1;i<=n;i++)
          printf "  %-*s  %-*s  %s\n", iw,issue[i], lw,location[i], problem[i]
      }')" || return 1

  step "=== Second opinion - round $round ==="
  printf '%s\n' "$rendered"
  return 0
}

# The final non-empty line of a gate's output must be its verdict.
gate_verdict() {
  printf '%s\n' "$1" | awk 'NF { line=$0 } END { print line }'
}

# Every finding line must carry exactly five tab-separated fields with a known
# severity, and the output must end with a well-formed verdict. Anything else is
# treated as an unavailable gate rather than a pass.
validate_gate_output() {
  local content="$1" marker="$2" verdict_prefix="$3"
  printf '%s\n' "$content" | awk -F'\t' -v marker="$marker" -v prefix="$verdict_prefix" '
    $1==marker {
      if (NF!=5) { bad=1; exit }
      if ($2!="CRITICAL" && $2!="HIGH" && $2!="MEDIUM" && $2!="LOW") { bad=1; exit }
      if ($3=="" || $4=="" || $5=="") { bad=1; exit }
    }
    NF { last=$0 }
    END {
      if (bad) exit 1
      if (last != prefix ": PASS" && last != prefix ": FAIL") exit 1
    }'
}

# Parse a user selection such as "1,3-5" into unique ascending indices.
#
# <allowed> is the space-separated list of run-wide numbers that may be picked,
# from finding_indices. It is a set rather than a maximum so that a number that
# does not exist is rejected rather than silently dropped -- if a developer
# mistypes, they should be told, not quietly handed a different fix. A range
# like 2-6 expands and then intersects, so it means "the findings in that span".
parse_selection() {
  local raw="$1" allowed="$2"
  printf '%s' "$raw" | tr ',' '\n' | awk -v allowed="$allowed" '
    BEGIN {
      count = split(allowed, list, " ")
      for (i=1; i<=count; i++) { ok[list[i]+0]=1; if (list[i]+0>max) max=list[i]+0 }
    }
    function emit(value) { if (value in ok) chosen[value]=1; else if (!ranged) bad=1 }
    {
      gsub(/[[:space:]]/, "")
      if ($0 ~ /^[0-9]+$/) { ranged=0; emit($0+0) }
      else if ($0 ~ /^[0-9]+-[0-9]+$/) {
        split($0, bounds, "-")
        ranged=1
        for (i=bounds[1]+0; i<=bounds[2]+0; i++) emit(i)
        ranged=0
      } else if ($0 != "") bad=1
    }
    END {
      if (bad) exit 1
      for (i=1; i<=max; i++) if (i in chosen) print i
    }'
}
