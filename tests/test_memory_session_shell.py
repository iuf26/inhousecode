"""The review gate's OpenViking session hook never affects the verdict.

memory_record_session runs at every verdict exit. These tests stub the Python
layer and check the contract that matters: off by default, outcome data reaches
the child process only through its environment, and every failure is one
warning line with exit status 0.
"""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(body: str, *, record_sessions: str = "1", fake_python: str = "") -> subprocess.CompletedProcess:
    with tempfile.TemporaryDirectory() as tmp:
        stub = Path(tmp) / "python3"
        stub.write_text("#!/usr/bin/env bash\n" + (fake_python or 'env | grep ^INHOUSECODE_OUTCOME_ | sort\necho \'{"status": "recorded"}\'\n'))
        stub.chmod(0o755)
        script = f"""
set -uo pipefail
INHOUSECODE_HOME={ROOT!s}
REPO_ROOT={ROOT!s}
INHOUSECODE_MEMORY_ENABLED=1
INHOUSECODE_MEMORY_RECORD_SESSIONS={record_sessions}
source "$INHOUSECODE_HOME/lib/common.sh"
source "$INHOUSECODE_HOME/lib/memory.sh"
resolve_python() {{ PYTHON_CMD=({stub!s}); }}
resolve_timeout() {{ return 1; }}
{body}
echo "rc=$?"
"""
        return subprocess.run(["bash", "-c", script], text=True, capture_output=True, check=False)


class RecordSessionShellTests(unittest.TestCase):
    def test_harvest_forwards_the_configured_auto_promotion_threshold(self):
        result = run(
            "INHOUSECODE_MEMORY_AUTO_PROMOTE_AFTER_REVIEWS=5\n"
            "memory_run() { printf '%s\\n' \"$@\"; }\n"
            "memory_harvest --lookback-days 14"
        )
        self.assertIn("harvest\n--auto-promote-after\n5\n--lookback-days\n14", result.stdout)

    def test_disabled_by_default_does_nothing(self):
        result = run('memory_record_session pass', record_sessions="0")
        self.assertIn("rc=0", result.stdout)
        self.assertNotIn("INHOUSECODE_OUTCOME_", result.stdout + result.stderr)

    def test_success_is_reported_and_status_zero(self):
        result = run(
            "AI_INITIAL_OUTPUT=$'##CR-FINDING##\\tHIGH\\ta.py:1\\tbug\\tFix it.'\n"
            "AI_OUTPUT=''\nAI_FIX_ROUNDS=1\nSTATIC_FIX_ROUNDS=2\nTARGET_MODE=staged\n"
            "memory_record_session overridden 'Legacy path kept on purpose'"
        )
        self.assertIn("rc=0", result.stdout)
        self.assertIn("review outcome sent to OpenViking", result.stdout + result.stderr)

    def test_child_receives_expected_variables(self):
        with tempfile.TemporaryDirectory() as tmp:
            dump = Path(tmp) / "env.txt"
            result = run(
                "AI_INITIAL_OUTPUT=$'##CR-FINDING##\\tHIGH\\ta.py:1\\tbug\\tFix it.'\n"
                "AI_OUTPUT=''\nAI_FIX_ROUNDS=1\nSTATIC_FIX_ROUNDS=2\nTARGET_MODE=staged\n"
                "memory_record_session overridden 'Legacy path kept on purpose'",
                fake_python=f"env | grep ^INHOUSECODE_OUTCOME_ > {dump}\necho '{{\"status\": \"recorded\"}}'\n",
            )
            self.assertIn("rc=0", result.stdout)
            env = dump.read_text()
        self.assertIn("INHOUSECODE_OUTCOME_VERDICT=overridden", env)
        self.assertIn("INHOUSECODE_OUTCOME_OVERRIDE_REASON=Legacy path kept on purpose", env)
        self.assertIn("INHOUSECODE_OUTCOME_FIX_ROUNDS=3", env)
        self.assertIn("INHOUSECODE_OUTCOME_TARGET=staged", env)
        self.assertIn("a.py:1", env)

    def test_failure_is_one_warning_and_status_zero(self):
        result = run(
            "AI_OUTPUT=$'##CR-FINDING##\\tHIGH\\ta.py:1\\tbug\\tFix.'\nmemory_record_session blocked",
            fake_python="echo 'inhousecode memory: OpenViking unavailable' >&2; exit 1\n",
        )
        self.assertIn("rc=0", result.stdout)
        combined = result.stdout + result.stderr
        self.assertIn("verdict is unaffected", combined)
        self.assertIn("OpenViking unavailable", combined)

    def test_python_missing_is_silent_and_status_zero(self):
        result = run(
            "resolve_python() { return 1; }\nmemory_record_session pass",
        )
        self.assertIn("rc=0", result.stdout)
        self.assertEqual(result.stderr, "")


if __name__ == "__main__":
    unittest.main()
