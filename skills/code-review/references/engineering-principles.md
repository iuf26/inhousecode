# Engineering principles

A minimal set of universal engineering principles the reviewer judges against.
Approved project and global knowledge in the frozen OpenViking snapshot governs
where it speaks; these principles cover the ground it does not address.

Kept deliberately short and chosen for *reviewing someone else's diff* — not for
authoring. Each principle lives in its own file under [`principles/`](principles/)
and gives the reviewer a concrete, checkable question. The adversarial lenses map
their findings to these by filename.

How to use these: a principle is a **lens**, not a rule. It tells you where to
look and what a real defect looks like. A violation is only a finding when you
can name the specific line and the concrete consequence — the same evidence bar
every other finding must clear. Never raise a finding that only says "this
violates a principle" without that grounding.

## The principles

### Architect lens — structure and boundaries

- [boundary-discipline](principles/boundary-discipline.md) — validation belongs
  at the seams; *is this data crossing a boundary right now?*
- [migrate-callers-then-delete-legacy-apis](principles/migrate-callers-then-delete-legacy-apis.md)
  — *are old paths actually deleted, or is this dual-path debt?*

### Skeptic lens — correctness and completeness

- [fix-root-causes](principles/fix-root-causes.md) — *symptom or actual cause?*
- [prove-it-works](principles/prove-it-works.md) — *is there a way to verify the
  claim, or is it a self-report / compile-only signal?*
- [make-operations-idempotent](principles/make-operations-idempotent.md) —
  *what happens if this runs twice, or crashes halfway?*
- [serialize-shared-state-mutations](principles/serialize-shared-state-mutations.md)
  — *shared mutable state without a lock or serialization story?*

### Minimalist lens — necessity and complexity

- [subtract-before-you-add](principles/subtract-before-you-add.md) — *could this
  be smaller, or deleted instead?* (a heuristic, not a veto)

### Operator lens — production safety

- [operate-safely](../../adversarial-review/references/principles/operate-safely.md)
  — *can this be deployed, observed, bounded, and reversed safely?*

### Calibration and follow-through

- [match-review-rigor-to-reversibility](principles/match-review-rigor-to-reversibility.md)
  — *how expensive is this to change later?* Push hard on the hard-to-reverse.
- [encode-lessons-in-structure](principles/encode-lessons-in-structure.md) —
  after the review: *am I writing this comment for the second time?* Promote a
  recurring finding to a rule.
