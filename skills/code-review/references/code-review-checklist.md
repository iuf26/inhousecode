# Code review checklist

The reviewer's **method and severity rubric**. Apply it *after* understanding
what the change is trying to do.

**The team rulebook comes first.** Concrete, citable rules live in
[developer-rulebook.md](developer-rulebook.md); check those first. This
checklist adds the judgment dimensions that are not fixed rules — correctness
edge cases, design cohesion, contract stability, test adequacy — plus the single
severity scale every finding uses.

**Precedence:** when a checklist prompt overlaps a rulebook rule, the **rulebook
wins**. Cite its `id`, use its severity, and do not report the issue twice. Use
this checklist's scale only for findings with no matching rulebook `id`.

**A static scanner already ran.** Do not re-report pattern-matchable lint. Every
finding here should be something that required reading and understanding the
code.

Cite the category name below as the finding `category` (or the rulebook `id`
when a rule applies).

## Correctness

- Off-by-one errors, wrong boundary conditions, inverted conditionals.
- Unhandled edge cases: empty input, null/None, zero, negative, very large values.
- Race conditions, unsafe concurrency, shared mutable state.
- Resource leaks: files, sockets, locks, or handles not closed or released.
- Incorrect error propagation beyond the rulebook's `error-handling` rule: the
  wrong error type raised, or an error caught and silently downgraded.

## Design & maintainability

- Single responsibility: a function, class, or module does one clear thing.
- Separation of concerns: business logic is not tangled with I/O or presentation.
- Consistent return shapes: predictable structures, not ad-hoc dictionaries.
- No dead code, commented-out blocks, or leftover debug statements.
- Naming and duplication belong to the rulebook (`readable-names`,
  `no-duplication`) — cite those `id`s instead of re-reporting here.

## AI-generated code smells

These are the failure modes that show up specifically in generated code. Weight
them accordingly.

- **Plausible but wrong**: an API, flag, or field that does not exist, or exists
  with different semantics than the code assumes.
- **Invented abstraction**: a wrapper, base class, or helper introduced for a
  single caller, adding indirection without value.
- **Silent scope creep**: files or behavior changed beyond what the task asked
  for.
- **Confident error handling**: a `try` that catches everything and returns a
  default, hiding the failure the caller needed to see.
- **Copy-drift**: near-duplicate logic pasted from elsewhere in the repo and
  edited slightly, so the two copies now disagree.
- **Test theater**: tests that assert the code ran rather than that it is right.

## Performance & scalability

- Database access avoids N+1 patterns, repeated queries in loops, and needless
  round trips where a set-based query would do.
- Queries and collection operations are bounded or paginated when input size can
  grow; the whole dataset is not loaded to use part of it.
- Repeated expensive computation, I/O, serialization, or network work is hoisted
  out of hot loops or reused when safe.
- The implementation is still practical at expected production volumes, not just
  on test-sized inputs.

## Interfaces & contracts

- Public signatures are stable, documented, and backward compatible unless the
  change intentionally breaks them — and that is called out.
- Inputs are validated at the boundary (rulebook `input-validation`); outputs
  match the documented contract.
- Changes to shared modules account for all existing callers.

## Security

Apply the rulebook's `no-secrets` rule first, then reason independently about:

- Injection: SQL, command, KQL, or template strings built from unsanitized input.
- Unsafe `eval`/`exec`/deserialization, or `subprocess(..., shell=True)` on
  untrusted input.
- Path traversal, SSRF, weak crypto, missing authorization, unsafe file
  permissions.

## Tests

- New behavior has tests; changed behavior updates existing tests.
- Tests assert real outcomes, not merely that the code ran without raising.
- Failure paths and edge cases are covered, not only the happy path.

## Severity guidance

The single scale for all findings, checklist and rulebook alike:

- **CRITICAL** — exploitable vulnerability, data loss, or a bug guaranteed to
  break production.
- **HIGH** — likely-incorrect behavior, a violated rulebook rule, or a security
  weakness.
- **MEDIUM** — a maintainability or design smell that should be fixed but does
  not block.
- **LOW** — a minor nit or style suggestion.

A violated rulebook rule takes its severity from the rulebook (**HIGH** by
default, unless marked advisory). CRITICAL and HIGH block; MEDIUM and LOW do not.

**When in doubt, go lower.** A gate that blocks on opinions gets disabled, and a
disabled gate reviews nothing.

Findings from this checklist are drafts. Every one of them still has to survive
the critique pass in [finding-critique.md](finding-critique.md) before it is
reported.
