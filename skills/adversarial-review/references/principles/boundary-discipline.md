# Boundary discipline

*Architect lens.*

Validation, type narrowing, and error handling belong at system boundaries (CLI
args, config parsing, external APIs, deserialization). Internal code trusts its
types.

The checkable question: *is this data crossing a boundary right now?*

- **Unvalidated input crossing a boundary** is a real defect — name the boundary
  and the input. Missing validation at the edge is HIGH when the input is
  attacker- or user-controlled.
- **Redundant re-validation deep inside** the system is noise that hides where
  the real check belongs; flag it MEDIUM at most, at the right seam.
- **Business logic tangled with framework wiring** — logic that cannot be tested
  without spinning up the whole shell — is a design finding: name the pure
  function that should have been extracted.
