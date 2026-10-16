# Subtract before you add

*Minimalist lens.*

A review heuristic, not a veto — plenty of correct PRs are pure additions.

The checkable question: *could this be smaller, or deleted instead?*

- **Dead weight is a finding.** Code the change leaves unreachable, a flag
  nothing reads, a branch that can no longer be taken — flag it with the reason
  it is now dead.
- **Half-finished is worse than absent.** A feature wired up but not functional,
  an API surface with no working implementation behind it — say what is
  incomplete.
- **Speculative complexity**: an abstraction for a single call site, a flag for a
  hypothetical need, configuration with no concrete second use case. Name the
  simpler shape — but hold this to a high bar; do not block a working addition
  merely for existing.
