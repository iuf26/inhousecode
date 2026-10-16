# Prove it works

*Skeptic lens.*

Verification is checking the real thing, not a proxy.

The checkable question: *does this PR include a way to verify its own claim — did
they run it, is there a test exercising the real path, or is it trusting a
self-report / compile-only signal?*

- **A test that asserts a proxy** — that a function was called, that a mock
  returned, that output is non-empty — rather than the actual behavior is a weak
  test. Say what it claims to prove versus what it checks.
- **A claim resting on a self-report or "it compiles"** rather than an exercised
  path is a gap worth a finding when the behavior is load-bearing.
- **An untested new behavior** on an error path or an integration seam is a gap
  worth a finding when that behavior is load-bearing.
