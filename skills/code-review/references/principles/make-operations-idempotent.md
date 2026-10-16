# Make operations idempotent

*Skeptic lens.*

The checkable question for any diff touching state mutation, retries, or startup
logic: *what happens if this runs twice, or crashes halfway?*

- **A non-idempotent operation a retry would double-apply** — an append with no
  dedupe key, a counter increment with no guard, a create that errors on
  re-run — is a real defect in any system that retries. Name the double-apply.
- **Startup or migration logic with no "already done" check** that corrupts on a
  second run is the finding.
