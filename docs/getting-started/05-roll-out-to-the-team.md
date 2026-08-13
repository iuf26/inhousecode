# 5. Roll it out to the team

Everything so far was one person, one clone. This page is the order that
gets a *team* to keep the gate turned on.

The short version: **don't start by blocking commits.** A gate that
interrupts people before they trust it is a gate that gets uninstalled by
the end of the week, and an uninstalled gate reviews nothing.

## The order that works

1. **Ship it read-only first.** Set `static.autofix: false` and
   `ai.autofixBlocking: false` in `.inhousecode/config.json`. Let the team see
   findings for a week without anything changing under them.
2. **Collect the disagreements.** Every "that's wrong" reply is either a rule
   that needs fixing or missing context the reviewer didn't have. Both are
   cheap to fix, and fixing them makes the next week quieter.
3. **Turn on static repair.** Semgrep findings are deterministic, so their
   fixes are too. This is where people first feel the tool save them time,
   not just flag them.
4. **Turn on AI repair for blocking findings.** By now the rulebook reflects
   how the team actually works, and the false-positive rate is low enough to
   trust the automatic fix.
5. **Only then consider agent-stop.** Once people trust the gate at commit
   time, move the check earlier — to the moment the code is generated, not
   the moment it's committed.

Do not start at step 5. Interrupting every agent turn before anyone trusts
the gate is the fastest way to get it deleted.

## Before you flip on step 4 or 5, check your Copilot quota

Every AI-phase run — review, repair, second opinion — spends Copilot premium
requests, and `agentStop` fires on **every turn**, not once per commit. Turning
that on for a team multiplies per-turn AI spend by headcount, not just by
commit count. Check your org's Copilot plan headroom before rolling either
step out wide, and read the itemized cost breakdown in
[architecture.md § What the run cost](../architecture.md#what-the-run-cost)
so you know what a run actually charges before a whole team starts running
it constantly. `agentStop.ai` defaults to `false` for this reason — the
static-only default is nearly free; the AI pass on every turn is not.

## Sharing the rulebook and config

Commit both:

```bash
git add .inhousecode/config.json .inhousecode/developer-rulebook.md
```

They belong in version control — that's the entire point of "in-house."
Everyone reviewing this repo, human or agent, reads the same rules.

For an organization with multiple repos, keep one canonical rulebook and
either vendor it into each repo or point `rulebook` at a shared path your
build populates; individual teams then append their own rules underneath the
shared block.

## Where the rules actually come from

Not a planning meeting. The best rules come from:

1. A review comment someone has typed more than twice.
2. A postmortem — write the rule that would have caught the incident.
3. Tribal knowledge a new hire currently only learns by breaking it.

The full playbook for writing good rules, what doesn't belong in the
rulebook, and severity guidance lives in
[docs/team-customization.md](../team-customization.md) — worth reading in
full once the gate is live and the team is actually using it.

## You're set up

That's the whole guided path. From here:

- [docs/configuration.md](../configuration.md) — every config option
- [docs/architecture.md](../architecture.md) — how the pipeline actually works
- [docs/team-customization.md](../team-customization.md) — the deep dive on
  rulebook craft and rollout
- [../../README.md](../../README.md) — full command reference
