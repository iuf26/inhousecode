# 3. Write your first rule

Don't design a rulebook. Write one rule — the one you're most tired of typing
in review comments — and see it work. The rest accumulates on its own after
that.

## Pick the rule

The best first rule is **a comment you've personally written more than
twice**. That repetition is the whole signal: if it comes up again and
again, it's worth a machine remembering it so you don't have to.

Something like "every query needs to filter by tenant" or "use the logging
module, not `print()`" — concrete, checkable, specific to how your team
actually works, not a general best practice a linter already covers.

## Write it

Open `.inhousecode/developer-rulebook.md` and add one line:

```markdown
- id (scope) — the rule
```

- `id` — short, kebab-case, unique. The reviewer will cite this exact string
  back to you on every finding, so `prefer-pathlib` is more useful than
  `rule-1`.
- `scope` — `all`, or a narrower area like `python`, `sql`, `tests`,
  `frontend`. The rule only applies to matching files — nothing else goes
  in this field.
- the rule itself — one imperative sentence you could check by eye. Blocking
  (**HIGH**) by default. End the line with `(MEDIUM)` or `(LOW)` if it should
  be flagged but never block a commit — a good default while you're still
  finding your footing.

A real first line:

```markdown
- tenant-scoped-queries (sql) — every query filters by tenant_id
```

## See it fire

Change some code that breaks the rule, then:

```bash
inhousecode review --worktree
```

The finding will now cite your rule by name and quote it back to you — not
a generic "this looks risky," but "this violates `tenant-scoped-queries`:
every query filters by tenant_id," pointed at the exact line.

## Keep going, slowly

Add rules the same way, one at a time, as you notice yourself repeating a
comment. Leave everything `(MEDIUM)` or `(LOW)` until you've watched it fire
correctly a few times — the full approach to promoting rules to blocking,
and to rolling this out to a whole team without it getting disabled in week
two, is in [docs/team-customization.md](../team-customization.md).

## Next

The rulebook only helps if it actually runs. Right now you're still typing
`inhousecode review` by hand — page 4 wires it into `git commit` or your
agent's stop event so it runs on its own:
[Turn on the hook](04-turn-on-the-hook.md).
