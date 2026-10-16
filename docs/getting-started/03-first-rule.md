# 3. Add your first piece of team knowledge

Don't design a policy. Add one fact — the review comment you are most tired of
typing — and watch it reach the reviewer.

## Pick it

The best first entry is **a comment you've written more than twice**, specific
to this repository and checkable by reading code. For example: "payment retries
must go through `with_idempotency_key()`" or "every SQL query filters by
`tenant_id`."

## Add it as a candidate

Everything starts as a candidate, even when a human writes it. Authorship is
provenance, not proof.

```bash
inhousecode memory candidate add \
  "Payment retries must go through with_idempotency_key()." \
  --source developer-feedback \
  --evidence payments/client.py:42
```

The command prints a candidate ID and the exact OpenViking URI it wrote and read
back.

## Classify it

```bash
inhousecode memory classify <candidate-id> \
  --target project --confidence high \
  --evidence payments/client.py:42
```

A repository-local, high-confidence, evidenced, non-security fact is promoted
to project knowledge automatically. Anything global, security-related, about
reviewer behavior, conflicting, or weakly evidenced stays classified until a
human runs `inhousecode memory promote`. The original candidate is kept either
way.

## See it fire

Change some code that breaks the fact, then:

```bash
inhousecode review --worktree
```

The reviewer receives the promoted record (with its stable URI and the snapshot
hash) and can cite it on the finding instead of giving generic advice.

Check what the team knows at any time:

```bash
inhousecode memory view --prompt "What do we know about payment retries?"
```

## Next

Knowledge only helps if review actually runs. Page 4 wires it into
`git commit` or your agent's stop event: [Turn on the hook](04-turn-on-the-hook.md).
