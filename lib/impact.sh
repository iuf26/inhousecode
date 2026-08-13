#!/usr/bin/env bash
#
# Blast-radius analysis.
#
# "Does this break anything?" is the question a diff cannot answer on its own,
# because the evidence lives in the files the diff does not touch. A reviewer
# who only sees the change can tell you the new code is well written; they
# cannot tell you the strategy it just modified has four other implementations
# and one of them no longer satisfies the interface.
#
# So the answer is precomputed here, deterministically, rather than left to the
# reviewer to go looking for. lib/impact.py names the contracts the change
# touched; this walks the rest of the repository for anyone still depending on
# them and hands the reviewer a map: for each changed contract, who else uses it
# and where.
#
# This is context, never a verdict. A referenced symbol is not a finding; it is
# a place the reviewer is now obliged to look before calling the change safe.

# --- named constants ---------------------------------------------------------
# Per symbol, how many call sites to name. Enough to see the shape of the
# dependency; not so many that one popular helper fills the prompt.
IMPACT_MAX_REFS_PER_SYMBOL=8
# A symbol referenced in more places than this is infrastructure. The exact
# list stops being useful and the count becomes the point.
IMPACT_WIDE_USE_THRESHOLD=40
# Total call sites across the whole report, so a sweeping rename cannot push
# the diff itself out of the model's context.
IMPACT_MAX_TOTAL_REFS=200
# Prose and data files mention names without depending on them. A doc line
# reading "emit the critique" is not a caller of emit(), and a report that
# says it is teaches the reviewer to distrust the whole map.
IMPACT_EXCLUDED_PATHSPEC=(
  ':(exclude)*.md' ':(exclude)*.markdown' ':(exclude)*.rst' ':(exclude)*.txt'
  ':(exclude)*.json' ':(exclude)*.yaml' ':(exclude)*.yml' ':(exclude)*.toml'
  ':(exclude)*.lock' ':(exclude)*.svg' ':(exclude)*.csv'
)

IMPACT_PATH=""

# impact_symbols <diff-path> <out-path>
# Writes 'kind<TAB>change<TAB>name' lines. Absence of output is normal: many
# changes declare nothing new.
impact_symbols() {
  local diff_path="$1" out_path="$2"
  [ -s "$diff_path" ] || return 1
  "${PYTHON_CMD[@]}" "$INHOUSECODE_HOME/lib/impact.py" "$diff_path" \
    > "$out_path" 2>/dev/null || return 1
  [ -s "$out_path" ]
}

# Every reference to <name> outside the files the change already touches.
#
# Searching the reviewed revision rather than the working tree keeps this
# consistent with what the rest of the gate is judging. Whole-word, fixed-string
# matching: a substring match on a short name would report half the repository.
impact_references() {
  local name="$1" rev="$2" scope_files="$3"
  local -a args=(grep --no-color -n -w -F -I --untracked)
  [ -n "$rev" ] && args=(grep --no-color -n -w -F -I "$rev")

  git "${args[@]}" -e "$name" -- . "${IMPACT_EXCLUDED_PATHSPEC[@]}" 2>/dev/null |
    if [ -n "$rev" ]; then sed "s|^$rev:||"; else cat; fi |
    awk -F: -v scope="$scope_files" '
      BEGIN { while ((getline path < scope) > 0) if (path != "") excluded[path]=1 }
      { file=$1 }
      !(file in excluded) { print }'
}

# impact_write_report <out-path>
# Sets IMPACT_PATH when there is something worth reading. Returns non-zero when
# the change declares nothing, or nothing outside it refers to what it declares
# -- in which case there is no map to draw and the reviewer is told so.
impact_write_report() {
  local out_path="$1"
  local symbols="$INHOUSECODE_CACHE_ROOT/impact-symbols.tsv"
  local scope_files="$INHOUSECODE_CACHE_ROOT/scan-files.txt"
  local rev="" total_refs=0 documented=0

  IMPACT_PATH=""
  [ -n "${AI_DIFF_PATH:-}" ] || return 1
  impact_symbols "$AI_DIFF_PATH" "$symbols" || return 1

  # In diff/PR mode the reviewed commit is authoritative and may not be checked
  # out; everywhere else the working tree is the subject.
  [ "$TARGET_MODE" = "diff" ] && [ "${DIFF_SOURCE:-commit}" = "commit" ] &&
    rev="${DIFF_HEAD:-HEAD}"

  {
    echo "# Blast radius of the changed contracts"
    echo "#"
    echo "# Every definition this change adds, modifies, or removes, followed by"
    echo "# the places OUTSIDE the change that still reference it. A reference is"
    echo "# not a finding: it is a caller whose assumptions this change may have"
    echo "# invalidated, and which you must check before calling the change safe."
    echo "#"
    echo "# removed  = gone or renamed. Every reference below is a break unless"
    echo "#            the change updated it or an alias was left behind."
    echo "# modified = the name survived; the signature, defaults, or semantics"
    echo "#            may not have. Check each reference against the new shape."
    echo "# added    = new surface. Check it does not duplicate or shadow"
    echo "#            something the references below already provide."
    echo
  } > "$out_path"

  local kind change name references count
  while IFS=$'\t' read -r kind change name; do
    [ -n "$name" ] || continue
    [ "$total_refs" -ge "$IMPACT_MAX_TOTAL_REFS" ] && break

    references="$(impact_references "$name" "$rev" "$scope_files")"
    count="$(printf '%s' "$references" | grep -c . 2>/dev/null || true)"
    count="${count:-0}"

    # New surface nothing else refers to yet is exactly what "added" means. It
    # tells the reviewer nothing, and forty such lines bury the contracts that
    # do. An added name that DOES collide with existing references is the case
    # worth reporting, and it survives this.
    [ "$change" = "added" ] && [ "$count" -eq 0 ] && continue

    printf '%s `%s` (%s) - %s external reference(s)\n' \
      "$kind" "$name" "$change" "$count" >> "$out_path"
    documented=$((documented + 1))

    if [ "$count" -eq 0 ]; then
      echo "    nothing outside the change refers to it." >> "$out_path"
    elif [ "$count" -gt "$IMPACT_WIDE_USE_THRESHOLD" ]; then
      # Widely used means the count *is* the finding: a change here is a
      # repository-wide event, and listing eight of forty call sites would
      # understate it.
      echo "    used repository-wide; treat any behavior change as breaking." >> "$out_path"
      printf '%s\n' "$references" | head -n "$IMPACT_MAX_REFS_PER_SYMBOL" |
        sed 's/^/    /' >> "$out_path"
      echo "    ..." >> "$out_path"
    else
      printf '%s\n' "$references" | head -n "$IMPACT_MAX_REFS_PER_SYMBOL" |
        sed 's/^/    /' >> "$out_path"
      [ "$count" -gt "$IMPACT_MAX_REFS_PER_SYMBOL" ] &&
        printf '    ... and %s more\n' "$((count - IMPACT_MAX_REFS_PER_SYMBOL))" >> "$out_path"
    fi
    echo >> "$out_path"
    total_refs=$((total_refs + count))
  done < "$symbols"

  [ "$documented" -gt 0 ] || return 1
  IMPACT_PATH="$out_path"
  return 0
}
