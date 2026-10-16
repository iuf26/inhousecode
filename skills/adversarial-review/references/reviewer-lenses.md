# Reviewer lenses

Three distinct adversarial perspectives. Each reviewer adopts one lens
exclusively — it does not try to be balanced. Every lens maps its findings to
this skill's engineering principles, one file each under
[`principles/`](principles/). Read the principle files your lens maps to before
reviewing.

## Skeptic

Challenge correctness and completeness. Ask:

- What inputs, states, or sequences will break this?
- What error paths are unhandled or silently swallowed?
- What race conditions or ordering dependencies exist? What shared state is
  mutated without a serialization story?
- What happens if this runs twice, or crashes halfway through?
- What does the author believe is true that isn't proven? Where is "it works on
  my machine" or "it compiles" masquerading as verification?

Maps to (see [`principles/`](principles/)):
[fix-root-causes](principles/fix-root-causes.md),
[prove-it-works](principles/prove-it-works.md),
[make-operations-idempotent](principles/make-operations-idempotent.md),
[serialize-shared-state-mutations](principles/serialize-shared-state-mutations.md).

## Architect

Challenge structural fitness. Ask:

- Does the design actually serve the stated intent, or a goal the author assumed?
- Where is data crossing a boundary without validation — or being re-validated
  needlessly deep inside?
- Where does responsibility leak between components? What coupling will hurt
  when requirements shift?
- Is this a refactor that added a new path but left the old one live? Are the
  legacy callers actually migrated and the old API deleted?

Maps to (see [`principles/`](principles/)):
[boundary-discipline](principles/boundary-discipline.md),
[migrate-callers-then-delete-legacy-apis](principles/migrate-callers-then-delete-legacy-apis.md),
[match-review-rigor-to-reversibility](principles/match-review-rigor-to-reversibility.md).

## Minimalist

Challenge necessity and complexity. Ask:

- What can be deleted without losing the stated intent?
- What is now dead — unreachable code, a flag nothing reads, a branch that can
  no longer be taken?
- What abstraction exists for a single call site? What configuration or
  flexibility was added with no concrete second use case?
- Is this the simplest path to the outcome, or the one that felt most thorough?

Maps to (see [`principles/`](principles/)):
[subtract-before-you-add](principles/subtract-before-you-add.md).
Hold this lens to a high bar — plenty of correct changes are pure additions, so
"it could be smaller" is an input, not a veto. Only raise a finding when the
complexity is genuinely unnecessary.

## Operator

Challenge whether the change can be safely deployed and operated. Ask:

- What happens during dependency failure, restart, timeout, retry, or overload?
- Is the operation bounded in time, memory, concurrency, queue growth, storage,
  network calls, and cost?
- Can the team detect the failure from existing metrics, logs, health checks, or
  alerts without leaking sensitive data?
- Can the change be rolled back without making the data state worse?
- Does it preserve compatibility between old and new versions during a rolling
  deployment?
- Does it require a migration, feature flag, runbook, dashboard, alert, or
  capacity change?

Maps to (see [`principles/`](principles/)):
[operate-safely](principles/operate-safely.md),
[make-operations-idempotent](principles/make-operations-idempotent.md),
[match-review-rigor-to-reversibility](principles/match-review-rigor-to-reversibility.md).

Run this lens when the changed code can affect a running service, deployment,
data migration, queue or worker, external dependency, resource limit, or
production configuration. Do not raise operational ceremony for a local or
non-running change with no production consequence.
