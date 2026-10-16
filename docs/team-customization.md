# Making it your team's reviewer

A general reviewer catches general problems. inhousecode becomes team-specific
through governed OpenViking knowledge, repository context, and deterministic
Semgrep packs.

## 1. Governed team knowledge

OpenViking is the only persistent memory store. Active records live under:

```text
viking://resources/inhousecode/memory-policy/
```

Feedback never becomes policy immediately. Add it as a candidate, classify it,
and promote it only when the evidence and scope are clear:

```bash
inhousecode memory candidate add \
  "Every payment write retry uses an idempotency key." \
  --source developer-feedback --evidence payments/client.py:42

inhousecode memory classify <candidate-id> --target project \
  --confidence high --evidence payments/client.py:42
```

Safe, well-evidenced repository facts may promote automatically. Global,
cross-repository, security-sensitive, conflicting, suppression-oriented, and
review-behavior changes require a human promotion decision. The original
candidate remains available after promotion.

Good knowledge is specific and testable:

- Every query in the billing service filters by `tenant_id`.
- Payment write retries use `with_idempotency_key()`.
- Public API errors use the repository's `ProblemDetails` shape.

Avoid vague preferences such as “write clean code.” If a linter or Semgrep rule
can enforce the requirement deterministically, use that instead.

Use `inhousecode memory view --prompt "<question>"` to inspect the project,
global, and candidate records available to the current repository. See
[memory-policy.md](memory-policy.md) for lifecycle and trust rules.

## 2. Repository context

The reviewer reads `AGENTS.md`, `CLAUDE.md`, or
`.github/copilot-instructions.md` as repository context: architecture, domain
terms, generated directories, test commands, and what “done” means. This
context helps the reviewer understand the code, but it does not bypass the
OpenViking candidate and promotion workflow for durable review policy.

## 3. Semgrep packs

`static.semgrepConfigs` controls Phase 1. The defaults are security-focused.
Teams with internal Semgrep rules can add those packs or repository paths.
Only configure sources that resolve successfully: one invalid `--config` makes
the static scan unavailable rather than silently dropping part of the floor.

## Repair policy

Start report-only:

```json
{
  "review": { "fixByDefault": false },
  "static": { "autofix": false },
  "ai": { "autofixBlocking": false }
}
```

After the team trusts the findings, enable deterministic static repair, then
blocking AI repair. Enable all-finding repair only as a deliberate final step:

```json
{
  "review": { "fixByDefault": true }
}
```

`--no-fix` always disables repair for one run, even when the repository default
is enabled. `--fix` enables all-finding repair for one run. Every repair is
bounded and re-reviewed; fixer agents never commit or push.

## Sharing across repositories

Commit `.inhousecode/config.json` when the team should share the same review
settings. Do not store memory records in the repository. Point each developer's
`ov` CLI at the same OpenViking service. Repository knowledge stays scoped to
its repository identity; approved global knowledge can apply across
repositories.

`.inhousecode/cache/` is transient review data and is ignored by `inhousecode
init`.
