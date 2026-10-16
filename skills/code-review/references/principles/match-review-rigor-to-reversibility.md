# Match review rigor to reversibility

*Calibration — applies across lenses. Reframed from foundational-thinking for a
reviewer.*

Not every line deserves equal scrutiny. Calibrate how hard you push to how hard
the decision is to undo.

The checkable question: *how expensive is this to change later?*

- **Push hard on the hard-to-reverse:** data models, persisted/serialized
  formats, public API shapes, and interface contracts. A weakness here is worth
  a finding even when the code "works", because fixing it later means a
  migration. State what future change it makes expensive.
- **Go easy on the easy-to-reverse:** an internal helper's shape, a local naming
  choice, a private implementation detail. Do not spend a HIGH finding on
  something a follow-up commit could trivially change. Simplicity nits at the
  code level are LOW at most.
- **The wrong data structure is a latent rewrite.** If the structure fights the
  dominant access pattern (a list scanned for lookups, a map iterated in an
  order it does not preserve), that is a real, hard-to-reverse defect — trace the
  access pattern and say which one the structure fights.
