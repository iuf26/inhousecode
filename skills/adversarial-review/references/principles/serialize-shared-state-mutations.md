# Serialize shared-state mutations

*Skeptic lens.*

The concurrency counterpart to idempotency.

The checkable question: *does this introduce shared mutable state without a lock
or serialization story?*

- **Concurrent access to shared state with no isolation** is a finding when a
  second actor could observe or modify it mid-operation. Name the state and the
  interleaving that breaks it.
- Do not invent races that cannot occur in the actual execution model — ground
  the finding in how the code is really run (event loop, thread pool, process
  model).
