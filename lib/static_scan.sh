#!/usr/bin/env bash
#
# Deterministic Semgrep scan over the review target.
#
# Materializes the in-scope files into an isolated tree and scans that tree, so
# staged mode sees exactly the blobs that will be committed rather than a dirty
# working tree. Prints one small JSON object on stdout describing the run; the
# caller reads that envelope and renders the report with static_report.py.
#
# Three modes, selected by environment variable (mutually exclusive):
#
#   normal (default)       materialize the tree and run semgrep in-process.
#   INHOUSECODE_STATIC_EMIT_ONLY=1
#                           materialize the tree and print the exact semgrep
#                           command for an external caller (an AI harness's
#                           own command-runner) to execute, instead of running
#                           it here. semgrep is never invoked by this process
#                           in this mode.
#   INHOUSECODE_STATIC_CONSUME_MODE=1 (+ INHOUSECODE_STATIC_CONSUME_REPORT)
#                           skip materializing the tree and running semgrep;
#                           validate a report an external caller already
#                           produced for the command emitted by a prior
#                           EMIT_ONLY run against the same INHOUSECODE_CACHE_ROOT.
#
# The EMIT_ONLY / CONSUME_MODE pair lets an AI harness run the deterministic
# Semgrep command itself, through its own terminal tool, instead of this
# script invoking semgrep as a hidden subprocess. Neither mode changes the
# finding contract or the "malformed/missing report is never a pass" rule --
# CONSUME_MODE applies the exact same report validation as the normal path.
#
# Inputs (environment):
#   INHOUSECODE_TARGET_MODE   staged | path | worktree | diff
#   INHOUSECODE_TARGET_PATH   path to scan when the mode is "path"
#   INHOUSECODE_DIFF_BASE     merge-base commit to diff against in "diff" mode
#   INHOUSECODE_DIFF_HEAD     commit under review in "diff" mode (default HEAD)
#   INHOUSECODE_DIFF_SOURCE   commit | worktree - where "diff" mode reads content.
#                          'worktree' is used once repairs are enabled, so each
#                          re-scan sees the fixes the previous round wrote.
#   INHOUSECODE_SEMGREP_CONFIGS  space-separated registry packs
#   INHOUSECODE_CACHE_ROOT    directory for scan artifacts
#   INHOUSECODE_STATIC_EMIT_ONLY        1 to emit the command instead of running it
#   INHOUSECODE_STATIC_CONSUME_MODE     1 to validate an externally produced report
#   INHOUSECODE_STATIC_CONSUME_REPORT   path to that report (consume mode only)
#
# Emitted JSON fields:
#   file_count     number  files in review scope
#   code_count     number  files eligible for semgrep
#   semgrep_json   string  path to the semgrep JSON report, or "none"
#   file_list      string  path to the newline-delimited in-scope file list
#   code_list      string  path to the semgrep-eligible subset
#   scan_target    string  isolated tree that was scanned, or "none"
#   scan_status    string  completed | skipped | unavailable | pending-external
#   scan_reason    string  short explanation of the status
#   target_mode    string  the review target mode
#   cache_root     string  INHOUSECODE_CACHE_ROOT, always present
#   external_argv  array|null  the exact command to run, in EMIT_ONLY mode with
#                  something to scan; null otherwise
#   external_report string|"none"  where that command must write its -o report

set -uo pipefail

JSON_CONTROL_CHAR_LIMIT=32

# Quote one string as a JSON string literal. Defined early: callers below
# (semgrep_argv_json) need it available before the scan logic runs.
json_quote() {
  local value="$1" output="" char code escaped index
  for ((index = 0; index < ${#value}; index++)); do
    char="${value:index:1}"
    case "$char" in
      '"') output+='\"' ;;
      '\') output+='\\' ;;
      $'\b') output+='\b' ;;
      $'\f') output+='\f' ;;
      $'\n') output+='\n' ;;
      $'\r') output+='\r' ;;
      $'\t') output+='\t' ;;
      *)
        printf -v code '%d' "'$char"
        if [ "$code" -lt "$JSON_CONTROL_CHAR_LIMIT" ]; then
          printf -v escaped '\\u%04x' "$code"
          output+="$escaped"
        else
          output+="$char"
        fi
        ;;
    esac
  done
  printf '"%s"' "$output"
}

REPO_ROOT="$(git rev-parse --show-toplevel)" || exit 1
cd "$REPO_ROOT" || exit 1

TARGET_MODE="${INHOUSECODE_TARGET_MODE:-staged}"
TARGET_PATH="${INHOUSECODE_TARGET_PATH:-}"
DIFF_BASE="${INHOUSECODE_DIFF_BASE:-}"
DIFF_HEAD="${INHOUSECODE_DIFF_HEAD:-HEAD}"
DIFF_SOURCE="${INHOUSECODE_DIFF_SOURCE:-commit}"
EMIT_ONLY="${INHOUSECODE_STATIC_EMIT_ONLY:-0}"
CONSUME_MODE="${INHOUSECODE_STATIC_CONSUME_MODE:-0}"
CONSUME_REPORT="${INHOUSECODE_STATIC_CONSUME_REPORT:-}"

# True when file content must come from git rather than the working tree.
reads_from_commit() {
  case "$TARGET_MODE" in
    staged) return 0 ;;
    diff)   [ "$DIFF_SOURCE" = "commit" ] ;;
    *)      return 1 ;;
  esac
}
CACHE_ROOT="${INHOUSECODE_CACHE_ROOT:-$REPO_ROOT/.inhousecode/cache}"
# EMIT_ONLY and CONSUME_MODE must agree on the scan tree / report location
# across two separate process invocations that share the same CACHE_ROOT, so
# they use a fixed subdirectory name instead of this process's own PID.
if [ "$EMIT_ONLY" = "1" ] || [ "$CONSUME_MODE" = "1" ]; then
  CACHE="$CACHE_ROOT/static-external"
else
  CACHE="$CACHE_ROOT/scan-$$"
fi

read -r -a SEMGREP_PACKS <<< "${INHOUSECODE_SEMGREP_CONFIGS:-p/security-audit}"
SEMGREP_ARGS=()
for pack in "${SEMGREP_PACKS[@]}"; do
  [ -n "$pack" ] && SEMGREP_ARGS+=(--config "$pack")
done

if ! mkdir -p "$CACHE"; then
  echo "static_scan: could not create cache directory '$CACHE'." >&2
  exit 1
fi

FILE_LIST="$CACHE/in-scope-files.txt"
CODE_LIST="$CACHE/semgrep-files.txt"

collect_files() {
  case "$TARGET_MODE" in
    staged)
      git diff --cached --name-only --diff-filter=ACMR > "$FILE_LIST"
      ;;
    worktree)
      # Everything the agent could have just written: modified tracked files
      # plus untracked, non-ignored files.
      {
        git diff --name-only --diff-filter=ACMR
        git diff --cached --name-only --diff-filter=ACMR
        git ls-files --others --exclude-standard
      } | sort -u > "$FILE_LIST"
      ;;
    path)
      {
        git ls-files -- "$TARGET_PATH"
        git ls-files --others --exclude-standard -- "$TARGET_PATH"
      } | sort -u > "$FILE_LIST"
      ;;
    diff)
      [ -n "$DIFF_BASE" ] || {
        echo "static_scan: diff mode requires INHOUSECODE_DIFF_BASE." >&2
        return 1
      }
      git diff --name-only --diff-filter=ACMR "$DIFF_BASE" "$DIFF_HEAD" | sort -u > "$FILE_LIST"
      ;;
    *)
      echo "static_scan: unknown target mode '$TARGET_MODE'." >&2
      return 1
      ;;
  esac
}

if ! collect_files; then
  echo "static_scan: could not enumerate the review target." >&2
  exit 1
fi

file_count="$(grep -c . "$FILE_LIST" 2>/dev/null)"
file_count="${file_count:-0}"

# Prose and binary assets are not Semgrep candidates. Extensionless scripts are
# included when they carry a shebang.
is_semgrep_candidate() {
  local file="$1" lower base first_line
  lower="$(printf '%s' "$file" | tr '[:upper:]' '[:lower:]')"
  base="${lower##*/}"
  case "$base" in
    dockerfile|dockerfile.*|containerfile|containerfile.*|jenkinsfile|makefile|gnumakefile|cmakelists.txt)
      return 0 ;;
  esac
  case "$lower" in
    *.py|*.pyi|*.js|*.jsx|*.mjs|*.cjs|*.ts|*.tsx|*.java|*.cs|*.go|*.rb|*.php|\
    *.c|*.h|*.cc|*.cpp|*.cxx|*.hpp|*.hxx|*.rs|*.kt|*.kts|*.swift|*.scala|\
    *.sh|*.bash|*.zsh|*.fish|*.lua|*.r|*.dart|*.ex|*.exs|*.erl|*.hrl|\
    *.tf|*.hcl|*.yaml|*.yml)
      return 0 ;;
  esac
  if [ "$TARGET_MODE" = "staged" ]; then
    first_line="$(git show ":$file" 2>/dev/null | sed -n '1p')"
  elif [ "$TARGET_MODE" = "diff" ] && reads_from_commit; then
    first_line="$(git show "$DIFF_HEAD:$file" 2>/dev/null | sed -n '1p')"
  else
    first_line="$(sed -n '1p' "$file" 2>/dev/null)"
  fi
  case "$first_line" in '#!'*) return 0 ;; esac
  return 1
}

: > "$CODE_LIST"
while IFS= read -r file; do
  [ -n "$file" ] && is_semgrep_candidate "$file" && printf '%s\n' "$file" >> "$CODE_LIST"
done < "$FILE_LIST"

code_count="$(grep -c . "$CODE_LIST" 2>/dev/null)"
code_count="${code_count:-0}"

semgrep_json="none"
scan_target="none"
scan_status="skipped"
scan_reason="no semgrep-eligible code in scope"
external_argv_json="null"
external_report="none"

materialize_scan_tree() {
  local target="$1" file
  local files=()
  while IFS= read -r file; do
    [ -n "$file" ] && files+=("$file")
  done < "$CODE_LIST"
  rm -rf "$target" && mkdir -p "$target" || return 1
  if [ "$TARGET_MODE" = "staged" ]; then
    git checkout-index -f --prefix="$target/" -- "${files[@]}" 2>/dev/null || return 1
  elif [ "$TARGET_MODE" = "diff" ] && reads_from_commit; then
    # Scan the reviewed commit, not the reviewer's working tree.
    for file in "${files[@]}"; do
      mkdir -p "$target/$(dirname "$file")" || return 1
      git show "$DIFF_HEAD:$file" > "$target/$file" 2>/dev/null || return 1
    done
  else
    for file in "${files[@]}"; do
      [ -f "$file" ] || continue
      mkdir -p "$target/$(dirname "$file")" && cp -- "$file" "$target/$file" || return 1
    done
  fi
}

# Build the exact semgrep invocation as a JSON array of strings, for an
# external caller (an AI harness) to run verbatim through its own
# terminal/exec tool. "env ..." sets the UTF-8 locale that keeps the finding
# contract byte-identical on every platform, matching the in-process call.
semgrep_argv_json() {
  local report="$1" tree="$2" out="[" first=1 part
  for part in env PYTHONUTF8=1 PYTHONIOENCODING=utf-8 semgrep \
      "${SEMGREP_ARGS[@]}" --metrics off --no-git-ignore --json -o "$report" -- "$tree"; do
    if [ "$first" -eq 1 ]; then first=0; else out+=","; fi
    out+="$(json_quote "$part")"
  done
  out+="]"
  printf '%s' "$out"
}

json_has_errors() {
  local report="$1"
  [ -s "$report" ] || return 0
  [ "${#JSON_READER[@]}" -gt 0 ] || return 0
  ! "${JSON_READER[@]}" -c \
    'import json,sys; sys.exit(1 if json.load(open(sys.argv[1], encoding="utf-8")).get("errors") else 0)' \
    "$report"
}

JSON_READER=()
if command -v python3 >/dev/null 2>&1 &&
    python3 -c 'import sys; raise SystemExit(sys.version_info.major != 3)' >/dev/null 2>&1; then
  JSON_READER=(python3)
elif command -v python >/dev/null 2>&1 &&
    python -c 'import sys; raise SystemExit(sys.version_info.major != 3)' >/dev/null 2>&1; then
  JSON_READER=(python)
elif command -v py >/dev/null 2>&1 && py -3 -c 'import sys' >/dev/null 2>&1; then
  JSON_READER=(py -3)
fi

if [ "$code_count" -gt 0 ] && [ "$EMIT_ONLY" = "1" ]; then
  # Materialize the tree -- a deterministic, local file/git operation -- but
  # leave running semgrep itself to the external caller.
  SCAN_TREE="$CACHE/scan-tree"
  scan_target="$SCAN_TREE"
  if ! materialize_scan_tree "$SCAN_TREE"; then
    echo "static_scan: could not materialize the scan tree." >&2
    exit 1
  fi
  report="$CACHE/semgrep.json"
  rm -f -- "$report"
  external_report="$report"
  external_argv_json="$(semgrep_argv_json "$report" "$SCAN_TREE")"
  scan_status="pending-external"
  scan_reason="scan command ready; run it, then resume with the report it writes"
  # Record what was actually scanned, so a later consume can detect the scan
  # tree changing underneath it (e.g. a second emit overwriting it, or a
  # stale cache directory reused for a different target) instead of
  # silently validating a report against content it does not describe.
  if command -v shasum >/dev/null 2>&1; then
    find "$SCAN_TREE" -type f -exec shasum -a 256 {} \; 2>/dev/null \
      | sort | shasum -a 256 | awk '{print $1}' > "$CACHE/scan-tree.sha256"
  elif command -v sha256sum >/dev/null 2>&1; then
    find "$SCAN_TREE" -type f -exec sha256sum {} \; 2>/dev/null \
      | sort | sha256sum | awk '{print $1}' > "$CACHE/scan-tree.sha256"
  fi
elif [ "$code_count" -gt 0 ] && [ "$CONSUME_MODE" = "1" ]; then
  # The tree and the command were already produced by a prior EMIT_ONLY run
  # against this same CACHE_ROOT. Validate the report exactly as the normal
  # path would -- a missing, empty, or error-carrying report is unavailable,
  # never a pass, whether semgrep ran in-process or externally.
  SCAN_TREE="$CACHE/scan-tree"
  scan_target="$SCAN_TREE"
  report="$CONSUME_REPORT"
  scan_tree_matches() {
    local recorded="$CACHE/scan-tree.sha256" current=""
    # Fail closed: no recorded hash (no shasum/sha256sum at emit time, or a
    # missing/corrupted cache directory) must never be treated as a match.
    [ -s "$recorded" ] || return 1
    if command -v shasum >/dev/null 2>&1; then
      current="$(find "$SCAN_TREE" -type f -exec shasum -a 256 {} \; 2>/dev/null \
        | sort | shasum -a 256 | awk '{print $1}')"
    elif command -v sha256sum >/dev/null 2>&1; then
      current="$(find "$SCAN_TREE" -type f -exec sha256sum {} \; 2>/dev/null \
        | sort | sha256sum | awk '{print $1}')"
    else
      return 1
    fi
    [ -n "$current" ] && [ "$current" = "$(cat "$recorded")" ]
  }
  if [ -n "$report" ] && [ -s "$report" ] && ! json_has_errors "$report" && scan_tree_matches; then
    semgrep_json="$report"
    scan_status="completed"
    scan_reason="scanned $code_count file(s) (external)"
  else
    scan_status="unavailable"
    if [ -z "$report" ] || [ ! -s "$report" ]; then
      scan_reason="the external static command was not run, or produced no report"
    elif [ "${#JSON_READER[@]}" -eq 0 ]; then
      scan_reason="Python 3 is required to validate the semgrep report"
    elif ! scan_tree_matches; then
      scan_reason="the scanned tree changed since 'static-check emit'; re-run emit"
    else
      scan_reason="semgrep reported scan errors"
    fi
  fi
elif [ "$code_count" -gt 0 ] && command -v semgrep >/dev/null 2>&1; then
  SCAN_TREE="$CACHE/scan-tree"
  scan_target="$SCAN_TREE"
  if ! materialize_scan_tree "$SCAN_TREE"; then
    echo "static_scan: could not materialize the scan tree." >&2
    exit 1
  fi

  report="$CACHE/semgrep.json"
  log="$CACHE/semgrep.stderr.log"
  rm -f -- "$report"
  # One scan unions every pack. The isolated tree is intentionally untracked, so
  # Git's ignore filter must be disabled or Semgrep would skip every file.
  PYTHONUTF8=1 PYTHONIOENCODING=utf-8 \
    semgrep "${SEMGREP_ARGS[@]}" --metrics off --no-git-ignore --json \
    -o "$report" -- "$SCAN_TREE" >/dev/null 2>"$log"
  semgrep_rc=$?

  if [ "$semgrep_rc" -eq 0 ] && [ -s "$report" ] && ! json_has_errors "$report"; then
    semgrep_json="$report"
    scan_status="completed"
    scan_reason="scanned $code_count file(s)"
  else
    scan_status="unavailable"
    if [ "$semgrep_rc" -ne 0 ]; then
      scan_reason="semgrep exited with status $semgrep_rc"
    elif [ "${#JSON_READER[@]}" -eq 0 ]; then
      scan_reason="Python 3 is required to validate the semgrep report"
    else
      scan_reason="semgrep reported scan errors"
    fi
  fi
elif [ "$code_count" -gt 0 ]; then
  scan_status="unavailable"
  scan_reason="semgrep is not installed"
  echo "static_scan: semgrep not found on PATH. Install it: pip install semgrep" >&2
fi

printf '{"file_count":%s,"code_count":%s,"semgrep_json":%s,"file_list":%s,"code_list":%s,"scan_target":%s,"scan_status":%s,"scan_reason":%s,"target_mode":%s,"cache_root":%s,"external_argv":%s,"external_report":%s}\n' \
  "$file_count" "$code_count" \
  "$(json_quote "$semgrep_json")" "$(json_quote "$FILE_LIST")" \
  "$(json_quote "$CODE_LIST")" "$(json_quote "$scan_target")" \
  "$(json_quote "$scan_status")" "$(json_quote "$scan_reason")" \
  "$(json_quote "$TARGET_MODE")" "$(json_quote "$CACHE_ROOT")" \
  "$external_argv_json" "$(json_quote "$external_report")"
