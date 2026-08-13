# 4. Turn on the hook

So far you've run `inhousecode review` by hand. This page makes it run on
its own, at one of two moments — pick either, or both.

## Option A: pre-commit (the classic gate)

Runs when you `git commit`, against your staged changes. You don't commit
until it's clean or you deliberately override.

```bash
inhousecode install-hooks --pre-commit
```

This writes a three-line shim to `.githooks/pre-commit` and points
`git config core.hooksPath` at it for this clone. Verify it took:

```bash
git config core.hooksPath        # expect: .githooks
inhousecode doctor                # "Installed triggers": pre-commit installed
```

**Don't commit the shim itself** — it hardcodes an absolute path to your
personal checkout, so it's meaningless on a teammate's machine:

```bash
echo '.githooks/' >> .gitignore
```

Each teammate runs `install-hooks` in their own clone; `core.hooksPath` is
local git config and can't be set on someone else's behalf anyway.

From here, `git commit` runs both phases against what's staged. Skip it once
with `git commit --no-verify`.

## Option B: agent-stop (the newer one)

Fires the moment your coding agent finishes a turn — Copilot CLI's
`agentStop` hook — and can hand findings straight back to the *same agent*,
with its context still loaded, before you ever see the output. No second
model, no diff to re-explain, feedback while the work is still warm.

```bash
inhousecode install-hooks --agent-stop
```

This one runs the static phase only by default (fast, fires often). Turn on
the AI phase there too once you trust it, in `.inhousecode/config.json`:

```json
{ "agentStop": { "ai": true } }
```

## Both at once

```bash
inhousecode install-hooks --pre-commit --agent-stop
```

Or just `inhousecode install-hooks` with no flags — it reads
`triggers` in `.inhousecode/config.json` and installs whichever one(s) are
turned on there.

## Turning it off

```bash
inhousecode uninstall-hooks
```

Removes the shims, unsets `core.hooksPath` if `.githooks/` ends up empty,
and leaves `.inhousecode/` — your rulebook and config — untouched.

## Next

This page covered the mechanics for *your* clone. Getting a whole team onto
this without the gate getting quietly disabled in week two is a matter of
order: [Roll it out to the team](05-roll-out-to-the-team.md).
