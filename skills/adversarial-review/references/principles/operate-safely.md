# Operate safely

A change is not ready merely because it works in a happy-path test. Ask whether
it can be deployed, observed, limited, and reversed without making the system or
its data worse.

Check the failure behavior of dependencies, restarts, timeouts, retries, partial
rollouts, and overload. Look for unbounded time, memory, concurrency, queue
growth, storage, network calls, or cost. Verify that important failures can be
seen through existing logs, metrics, health checks, or alerts without exposing
secrets or personal data.

For migrations, APIs, configuration, and other deployed contracts, check
compatibility between old and new versions during a rolling deployment. Ask
whether rollback is safe after the change has written data. Require a concrete
migration, feature flag, runbook, dashboard, alert, or capacity change when the
operational consequence makes one necessary.

Raise a finding only when the changed code creates a specific operational risk
and cite the line and failure mechanism. Do not demand operational ceremony for
a local or non-running change with no production consequence.
