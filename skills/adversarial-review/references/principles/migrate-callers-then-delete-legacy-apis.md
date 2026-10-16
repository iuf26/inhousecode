# Migrate callers, then delete legacy APIs

*Architect lens.*

A refactor is not done when the new path works — it is done when the old one is
gone.

The checkable question: *are old paths actually deleted, or is this dual-path
debt sneaking in?*

- **A new path added beside the old, with both live**, is the finding — name the
  legacy path that should have been removed and the callers still on it.
- **A rename or signature change with no caller migration** leaves the codebase
  half-converted; point at the callers left behind.
- Dual-path debt is worth a finding even when the new code is correct: two ways
  to do one thing is a maintenance trap and a source of drift.
