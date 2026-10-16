# Testing inhousecode by hand

A manual acceptance path. Every step below was run during development and the
expected output is what it actually produced — if you see something different,
that is a real regression, not a doc that drifted.

Total time: ~10 minutes, most of it waiting on two model calls.

- [0. Static checks on the tool itself](#0-static-checks-on-the-tool-itself)
- [1. Environment](#1-environment)
- [2. Phase 1 alone — report only](#2-phase-1-alone--report-only)
- [3. The repair loop](#3-the-repair-loop)
- [3b. Fix-by-default and override precedence](#3b-fix-by-default-and-override-precedence)
- [4. Phase 2 alone — the reviewer](#4-phase-2-alone--the-reviewer)
- [5. The finding picker](#5-the-finding-picker)
- [5b. The explain handoff](#5b-the-explain-handoff)
- [6. The pre-commit trigger, for real](#6-the-pre-commit-trigger-for-real)
- [7. The agentStop trigger](#7-the-agentstop-trigger)
- [8. Pull-request mode (`--pr` and `--diff`)](#8-pull-request-mode---pr-and---diff)
- [9. Install and uninstall](#9-install-and-uninstall)
- [10. Reset](#10-reset)
- [Line endings](#line-endings)
- [Coverage](#coverage)

On Windows run everything from Git Bash, not PowerShell — the CLI and hooks are
bash — and write paths in Git Bash form (`/c/Users/you/src/...`).

Set these once per shell, pointing at wherever you keep the two checkouts:

```bash
INHOUSECODE=~/src/inhousecode        # this repository
DEMO=~/projects/code-sentinel-demo   # the demo repo: one service seeded with real defects
```

The demo repository is described in
[client-trial.md](client-trial.md#trying-it-on-the-demo-repository).

Every step below is written against those two variables, so nothing else in this
page needs editing.

---

## 0. Static checks on the tool itself

No models, no network. Run this first — it catches every syntax-level break.

```bash
cd "$INHOUSECODE"
for f in bin/inhousecode lib/*.sh hooks/*.sh install.sh; do
  bash -n "$f" || echo "SYNTAX-FAIL $f"
done
python -m py_compile lib/*.py && echo ALL-SYNTAX-OK
```

**Expect:** `ALL-SYNTAX-OK`, no `SYNTAX-FAIL` lines.

Then confirm the config resolver renders shell assignments:

```bash
python lib/config.py . .
```

**Expect:** `INHOUSECODE_*=...` lines, starting `INHOUSECODE_HARNESS=copilot`.
A traceback here means `config.py`, `review.config.default.json`, and
`review.config.schema.json` have drifted apart.

---

## 1. Environment

```bash
cd "$DEMO"
bash "$INHOUSECODE/bin/inhousecode" doctor
```

**Expect:** `OK` on git repository, python 3, semgrep, AI harness, timeout.

Two failures worth knowing:

- **The configured harness resolves to a path containing
  `globalStorage/github.copilot-chat`.** That is VS Code's internal Copilot
  copy and it cannot run headless. `harness_resolve_bin` in
  `lib/harness_copilot.sh` is supposed to skip it. If `doctor` reports that
  path, the skip is broken.
- **`python3` not found but `python` works.** Expected on Windows, where the
  Python launcher installs as `python`, not `python3`. `resolve_python` probes
  with `-c` rather than `command -v` for exactly this reason.

---

## 2. Phase 1 alone — report only

The fastest end-to-end signal. No model call.

```bash
cd "$DEMO"
bash "$INHOUSECODE/bin/inhousecode" review --path src --mode static --no-fix
echo "EXIT=$?"
```

**Expect** — 3 findings, 1 blocking, and `EXIT=1`:

```
  #    SEVERITY  LOCATION                CATEGORY                     FIX
  1    CRITICAL  src/user_service.py:40  subprocess-shell-true        Found 'subprocess' function 'call' with 'shell=True'.
  2    MEDIUM    src/user_service.py:34  insecure-hash-algorithm-md5  Detected MD5 hash algorithm which is considered insecure.
  3    MEDIUM    src/user_service.py:34  md5-used-as-password         It looks like MD5 is used as a password hash.
```

**What this proves:** scan → contract → parse → render → exit code, plus that
`--no-fix` really does not edit anything (`git status` stays clean).

**Watch for:** any line beginning `LIST:` or `Vulnerabilities found:` leaking
into the terminal. That scaffolding was removed; its return means
`static_report.py` regained a second source of truth for the summary.

---

## 3. The repair loop

The headline behavior. Costs one model call (~1 min).

```bash
cd "$DEMO"
printf 'import subprocess\ndef purge(uid):\n    subprocess.call("rm -rf /data/" + str(uid), shell=True)\n' > src/scratch.py
bash "$INHOUSECODE/bin/inhousecode" review --path src/scratch.py --mode static --gate
echo "EXIT=$?"
cat src/scratch.py
```

**Expect:** 1 CRITICAL, then `Static repair round 1/20`, then a clean re-scan,
`Static analysis: 1 repair round(s) applied.`, and `EXIT=0`.

**Judge the fix, not just the exit code.** This is the difference between the
tool being useful and being a nuisance. A passing run that produced
`shell=False` and nothing else is a *weak* result — the command is still built
by string concatenation. A good result rejects unsafe input or resolves and
confines the path. During development this step produced a `os.path.realpath`
containment check plus a `ValueError` on escape, which is the standard to hold
it to.

**Then check it honored the house style**, which is the other half of a good
fix. Put something in `AGENTS.md` that the finding says nothing about:

```bash
cat >> AGENTS.md <<'EOF'
- Every module-level constant is UPPER_SNAKE and grouped at the top of the file.
- Every function performing destructive I/O logs via `LOGGER` before acting.
EOF
printf 'import subprocess\ndef purge(uid):\n    subprocess.call("rm -rf /data/" + str(uid), shell=True)\n' > src/scratch.py
bash "$INHOUSECODE/bin/inhousecode" review --path src/scratch.py --mode static --gate
grep -n 'LOGGER' src/scratch.py
```

**Expect** a `LOGGER = logging.getLogger(__name__)` constant at the top and a log
line before the deletion. Semgrep said only "shell=True" — nothing about logging.
If those appear, `craft_standard()` reached the fixer; if the fix is technically
correct but stylistically foreign, it did not.

The fixer must also never **stall**. It runs with `--no-ask-user`, so an agent
that decides to ask a question gets no answer and burns the round. A round that
times out with no edit is this failing, not the model being slow.

Clean up:

```bash
rm src/scratch.py
git checkout -- AGENTS.md
```

## 3b. Fix-by-default and override precedence

Use a disposable trial branch. Set `review.fixByDefault` to `true`, create one
static and one AI-review defect, and run each supported target. Confirm a fixer
runs for staged, worktree, path, and a checked-out diff/PR head. A diff or PR
whose reviewed commit is not checked out must warn and stay report-only.

Then record the tree hash and run both flag orders:

```bash
git status --porcelain=v1 > /tmp/inhousecode-before.txt
inhousecode review --worktree --fix --no-fix --gate || true
inhousecode review --worktree --no-fix --fix --gate || true
git status --porcelain=v1 > /tmp/inhousecode-after.txt
cmp /tmp/inhousecode-before.txt /tmp/inhousecode-after.txt
```

**Expect:** both runs are report-only and `cmp` exits 0. `--no-fix` has
precedence regardless of order. Set `review.fixByDefault` back to `false` after
the check.

---

## 4. Phase 2 alone — the reviewer

Costs one model call (~2-4 min).

```bash
cd "$DEMO"
bash "$INHOUSECODE/bin/inhousecode" review --path src --mode ai --no-fix --gate
echo "EXIT=$?"
```

**Expect:** findings and a blocking exit for the seeded defects. Verify three things:

1. **Promoted knowledge is attributed.** A finding caused by a promoted project
   or global record names that rule and provenance. Built-in findings say
   `built-in AI review guidance`; they must not pretend to use memory.
2. **The SQL injection on `src/user_service.py:20` is reported.** Semgrep misses
   it. If Phase 2 misses it too, nothing is covering it.
3. **Severity split is sane** — CRITICAL/HIGH for injection, secrets, and
   swallowed exceptions; MEDIUM/LOW for naming and N+1.

**The failure mode to watch for** is not a wrong finding — it is
`AI code review : unavailable - the reviewer produced no valid verdict`
alongside prose that clearly *describes* findings. That means the model wrote a
summary instead of `##CR-FINDING##` lines. It is why the output contract is
restated inline in every prompt rather than left in `SKILL.md`, which the model
may be unable to read. Treat any recurrence as a prompt regression.

`unavailable` blocks. It must never pass.

---

## 5. The finding picker

Needs a **real terminal** — this is the one step that cannot be scripted, since
it is deliberately skipped when there is no TTY.

```bash
cd "$DEMO"
bash "$INHOUSECODE/bin/inhousecode" review --path src --mode ai
```

**First check that there is exactly one table.** The report lists every finding
once, numbered, with a severity column; the picker prompts against that table
rather than reprinting a subset. A second table is the regression to watch for —
it renumbers from 1, so the same finding reads as `#3` in one and `#1` in the
other, and a developer who trusts the first one silently gets a different fix
applied.

**Then check that every number is offered.** The header names the blocking ones
in red, but the prompt's `Pick from:` list must contain *all* rows in the table,
blocking included. A picker that only accepts the non-blocking numbers is the
old behavior and is a regression — the findings that matter most were the ones
you could not act on.

At the prompt, try in order: `n` (fix none), then re-run and pick two
non-blocking numbers, then re-run and pick a *blocking* number, then `99` and
`abc`.

**Expect:** `n` exits without editing; picked numbers fix exactly the findings
carrying those numbers in the table; out-of-range and non-numeric input are
rejected with a re-prompt rather than being treated as "all"; a range like `2-7`
selects every finding inside it. `a` selects the whole table. Reset with
`git checkout -- .` between attempts.

**After picking anything**, a second report headed
`=== AI review (after your fixes) ===` must appear — every time, not only when a
blocking finding was picked. Without it the verdict describes code that no longer
exists: `PASS` on edits no gate ever saw, which is the hole
[invariant 8](../AGENTS.md#invariants) closes for explain sessions. If
findings remain, the picker must offer the **new** list
rather than stopping at a report you cannot act on.

Pick `a` repeatedly to confirm this terminates: either the review comes back
clean (`No findings.`, no dangling prompt) or the budget message appears after
`ai.maxFixLoops` rounds. An unbounded prompt loop is the regression to watch for.

---

## 5b. The explain handoff

Two halves that must be verified separately, because the first one has to work
even when the second cannot run.

**The briefing (no model, no terminal needed):**

```bash
cd "$DEMO"
bash "$INHOUSECODE/bin/inhousecode" review --path src --mode static --no-fix --gate
bash "$INHOUSECODE/bin/inhousecode" explain          # no TTY here
cat .inhousecode/cache/last-briefing.md
```

**Expect:** `explain` refuses to launch, prints the briefing path, and exits 0.
The briefing lists every finding with its severity, the applicable rule and
provenance, and a numbered source excerpt with `>` on the offending line.

The briefing must exist even though `--gate` never prompted. Then confirm a
clean run clears it:

```bash
bash "$INHOUSECODE/bin/inhousecode" review --path tests --mode static --no-fix --gate
test -f .inhousecode/cache/last-briefing.md && echo "STALE - bug" || echo "cleared"
```

**Expect:** `cleared`. A briefing that explains findings you already fixed is
worse than no briefing.

Check the staged/worktree distinction, which is easy to get wrong:

```bash
git add src/<some-file>
echo "# dirt" >> src/<some-file>        # worktree now differs from the index
bash "$INHOUSECODE/bin/inhousecode" review --staged --mode static --no-fix --gate
grep '^>' .inhousecode/cache/last-briefing.md
```

**Expect:** the marked line shows the **staged** content, not the dirtied
working-tree line. An excerpt from disk in staged mode would show lines that
were never reviewed.

**The session (needs a real terminal):** re-run a blocking review and press `e`.

**Expect:** an interactive session opens in your configured harness; its first
turn is one short block per finding (one sentence per field, no preamble, no
closing summary) and it ends by asking which to fix. It edits nothing until
you answer. On exit, inhousecode reports blocked and asks you to re-run — even
if the session fixed everything, because nothing has re-reviewed those edits.

With `explain.enabled: false`, the `[e]` option must disappear from both the
blocked prompt and the finding picker, and `inhousecode explain` must refuse.

---

## 6. The pre-commit trigger, for real

The full flow, both phases, through git. ~5 min.

```bash
cd "$DEMO"
bash "$INHOUSECODE/bin/inhousecode" install-hooks --pre-commit
git config core.hooksPath          # expect: .githooks

printf 'import subprocess\ndef run(cmd):\n    subprocess.call(cmd, shell=True)\n' > src/runner.py
git add src/runner.py
git commit -m "add runner"
echo "COMMIT-EXIT=$?"
```

**Expect:** Phase 1 finds the CRITICAL, repairs it, re-scans clean, Phase 2 runs
and reports only non-blocking findings, `PASS`, and the commit **succeeds** with
`COMMIT-EXIT=0`.

Then confirm the repair was actually committed, not just written to disk:

```bash
git show --stat HEAD
git show HEAD:src/runner.py | grep -c 'shell=True'    # expect: 0
```

That last check is the one that matters. A fix that lands in the working tree but
not in the index would let the vulnerable version be committed while the terminal
says `PASS` — the worst possible outcome for this tool. It is what
`static_restage` exists to prevent.

Now check the blocking path, with repair disabled:

```bash
printf 'import subprocess\ndef go(c):\n    subprocess.call(c, shell=True)\n' > src/bad.py
git add src/bad.py
INHOUSECODE_STATIC_AUTOFIX=0 git commit -m "should be blocked"
echo "COMMIT-EXIT=$?"     # expect: non-zero
git log --oneline -1      # expect: still the previous commit
```

And confirm the escape hatch works:

```bash
git commit -m "bypass" --no-verify && git reset --hard HEAD~1
```

---

## 7. The agentStop trigger

Test it without a Copilot session by feeding it a payload directly.

```bash
cd "$DEMO"
printf 'import subprocess\ndef purge(uid):\n    subprocess.call("rm -rf /data/" + str(uid), shell=True)\n' > src/generated.py

cd "$INHOUSECODE"
printf '{"sessionId":"t1","cwd":"%s","stopReason":"end_turn"}' "$DEMO" |
  bash hooks/agent-stop.sh
echo "HOOK-EXIT=$?"
```

**Expect:** exactly one JSON object on stdout and `HOOK-EXIT=0`:

```json
{"decision": "block", "reason": "inhousecode reviewed the code from this turn and found issues.\n\n...\n\n- [semgrep][CRITICAL] src/generated.py:3 | subprocess-shell-true | ...\n\nAttempt 1 of 20."}
```

Four properties to check:

- **Exactly one JSON object.** The Copilot CLI concatenates non-progress stdout
  and parses it as a single document. Two objects, or any stray text, breaks it.
- **Exit status is 0 even when blocking.** The decision travels in the JSON, not
  the exit code.
- **`Attempt N of 20` increments** across repeated runs with the same
  `sessionId`, and the hook stops blocking at 20.
- **Silence is a valid answer.** With a clean tree it should print nothing and
  exit 0.

That last property is also the dangerous one: this hook fails open by design, so
a bug looks identical to "nothing to report". If you change `agent-stop.sh`,
always re-run it against a *known-bad* file and confirm you still get JSON. A
silent regression here was the most serious bug found during development —
`static_report.py` exits 1 by design on findings, and the `ERR` trap read that as
an internal fault and gave up, so the hook never fired on any real finding.

To trace a silent exit:

```bash
printf '{"sessionId":"t1","cwd":"%s","stopReason":"end_turn"}' "$DEMO" |
  bash -x hooks/agent-stop.sh 2>&1 | tail -40
```

The last `+` line before `give_up` is the culprit.

Optionally exercise the AI pass too — slow, one model call per turn:

```bash
cd "$DEMO"
# add "agentStop": { "ai": true } to .inhousecode/config.json first
```

---

## 8. Pull-request mode (`--pr` and `--diff`)

Reviews the commits a branch adds on top of its base, from the **committed**
blobs of the reviewed commit — a dirty working tree must not reach the scanner,
and the PR must not need to be checked out.

### `--pr`, against a real forge

```bash
cd <a clone with a GitHub or Azure DevOps remote>
git switch main                      # deliberately NOT the PR branch
inhousecode review --pr <id> --mode static --gate
git rev-parse --abbrev-ref HEAD      # expect: still main
```

**Expect:** a `PR #<id> - <title>` header, `<sha> -> <base-branch>` resolved
without you naming the base, `[PR #<id> vs <base>]` in the run header, the
report-only notice, and your checkout untouched.

Check the three resolution paths:

- **`gh` / `az` authenticated** — the base branch comes from the forge. Point it
  at a PR that targets something other than the default branch; the header must
  show that branch, not the default.
- **CLI unavailable** (`PATH= inhousecode review --pr <id>`) — falls back to
  `refs/pull/<id>/head` and *warns* that it assumed the default branch. A silent
  fallback here would be a wrong review presented as a right one.
- **Unresolvable** (`--pr 999999`, `--pr abc`) — exit 2 with a fix-it hint.
  Never a pass.

### `--diff`, without a forge

```bash
cd "$DEMO"
BASE="$(git rev-parse --abbrev-ref HEAD)"
git checkout -b pr-demo
printf 'import subprocess\ndef go(c):\n    subprocess.call(c, shell=True)\n' > src/pr.py
git add src/pr.py && git commit -qm "pr change"

printf 'WORKTREE_ONLY = 1\n' > src/pr_dirty.py       # untracked: must stay out of scope
inhousecode review --diff "$BASE" --mode static --gate
echo "EXIT=$?"
```

**Expect:** header `[diff vs <BASE> @ <sha>]`, a file count that **excludes**
`src/pr_dirty.py`, the CRITICAL in `src/pr.py`, `EXIT=1`, and `git status` still
showing `src/pr_dirty.py` untracked and unmodified.

Three properties that must hold for both:

- **Merge base, not base tip.** Commit something on `$BASE` after branching; the
  next run must not attribute it to the branch under review.
- **Report-only by default.** No file is edited without `--fix` or
  `review.fixByDefault: true`; explicit `--no-fix` overrides both. Repair is
  refused outright when the reviewed commit is not checked out.
- **The AI gate reads the reviewed commit.** With a PR that is not checked out,
  `.inhousecode/cache/run-*/review-tree` must contain the PR's version of each
  changed file, and the prompt's `Reviewed source root:` must point at it — not
  at the repository root.

Clean up: `git checkout "$BASE" && git branch -D pr-demo && rm -f src/pr_dirty.py`

---

## 9. Install and uninstall

```bash
cd "$DEMO"
bash "$INHOUSECODE/bin/inhousecode" install-hooks --pre-commit --agent-stop
bash "$INHOUSECODE/bin/inhousecode" doctor | tail -4   # both "installed"
cat .github/hooks/inhousecode.json                  # valid JSON, absolute path
bash "$INHOUSECODE/bin/inhousecode" uninstall-hooks
bash "$INHOUSECODE/bin/inhousecode" doctor | tail -4   # both "not installed"
```

Also confirm `init` never destroys repository configuration:

```bash
cp .inhousecode/config.json /tmp/inhousecode-config-before.json
bash "$INHOUSECODE/bin/inhousecode" init
cmp .inhousecode/config.json /tmp/inhousecode-config-before.json
```

**Expect:** `already exists; leaving it alone.` and `cmp` exits 0. Memory records
live in OpenViking and must not be recreated under `.inhousecode/`.

---

## 10. Reset

```bash
cd "$DEMO"
git reset --hard HEAD && git clean -fdx
git config --unset core.hooksPath
```

`git clean -fdx` removes untracked files. Commit anything you want to keep
first.

---

## Line endings

After editing any script on Windows:

```bash
cd "$INHOUSECODE"
file bin/inhousecode lib/*.sh hooks/*.sh
```

**Expect:** `Bourne-Again shell script, ASCII text executable` — with **no**
`with CRLF line terminators`. CRLF breaks the shebang. `.gitattributes` pins LF
on checkout, but an editor can still reintroduce it. To fix:

```bash
perl -pi -e 's/\r\n/\n/' bin/inhousecode lib/*.sh lib/*.py hooks/*.sh install.sh
```

---

## Coverage

| Area | Covered by |
|---|---|
| Syntax, config schema | 0 |
| Tool resolution | 1 |
| Scan → contract → render | 2 |
| Static repair loop | 3 |
| House style honored by fixers (`craft_standard`) | 3 |
| AI review, governed memory, contract | 4 |
| Interactive finding triage | 5 |
| Explain briefing, staged excerpts, session handoff | 5b |
| Pre-commit, restaging, bypass | 6 |
| agentStop, block budget, fail-open | 7 |
| PR review mode, merge-base scoping, forge resolution | 8 |
| Installers, `init` safety | 9 |

Not covered by this path: `install.ps1` and the `inhousecode.cmd` shim, macOS
and Linux (`gtimeout`, `python3`), Semgrep pack availability changes — a
`--config` pointing at a pack that has been removed from the registry makes
Semgrep exit non-zero and discards the entire scan — the `claude-code` and
`hermes` harness adapters (this path was written and run against `copilot`
only), and `inhousecode discover` / `inhousecode memory`.
