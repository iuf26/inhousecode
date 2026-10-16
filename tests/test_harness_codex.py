"""The Codex harness adapter preserves the gate's trust boundaries."""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADAPTER = ROOT / "lib" / "harness_codex.sh"


class CodexHarnessTests(unittest.TestCase):
    def run_adapter(self, function: str) -> list[str]:
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / "codex"
            args = Path(tmp) / "args"
            stdin = Path(tmp) / "stdin"
            fake.write_text(
                "#!/usr/bin/env bash\n"
                f"printf '%s\\n' \"$@\" > {args!s}\n"
                f"cat > {stdin!s}\n"
                "printf '%s\\n' '{\"type\":\"item.completed\",\"item\":{\"type\":\"agent_message\",\"text\":\"ok\"}}'\n"
            )
            fake.chmod(0o755)
            log = Path(tmp) / "run.jsonl"
            script = f"""
set -uo pipefail
HARNESS_BIN={fake!s}
TIMEOUT_BIN=
REPO_ROOT={ROOT!s}
source {ADAPTER!s}
{function} 'PROMPT BODY' {log!s} 60 'model-x' 0
printf 'rc=%s\n' "$HARNESS_RC"
"""
            result = subprocess.run(["bash", "-c", script], text=True, capture_output=True, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("rc=0", result.stdout)
            self.assertEqual(stdin.read_text(), "PROMPT BODY")
            return args.read_text().splitlines()

    def run_explain(self) -> list[str]:
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / "codex"
            args = Path(tmp) / "args"
            fake.write_text(
                "#!/usr/bin/env bash\n"
                f"printf '%s\\n' \"$@\" > {args!s}\n"
            )
            fake.chmod(0o755)
            script = f"""
set -uo pipefail
HARNESS_BIN={fake!s}
REPO_ROOT={ROOT!s}
source {ADAPTER!s}
harness_explain_cmd 'PROMPT BODY' 'model-x'
"""
            result = subprocess.run(
                ["script", "-q", "/dev/null", "bash", "-c", script],
                text=True, capture_output=True, check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            return args.read_text().splitlines()

    def test_review_is_read_only_ephemeral_and_ignores_repository_instructions(self):
        args = self.run_adapter("harness_review_cmd")
        self.assertIn("read-only", args)
        self.assertIn("--ephemeral", args)
        self.assertIn("--ignore-user-config", args)
        self.assertIn("--ignore-rules", args)
        self.assertIn("--json", args)
        self.assertNotIn("workspace-write", args)

    def test_fixer_is_workspace_write_but_still_ephemeral(self):
        args = self.run_adapter("harness_fix_cmd")
        self.assertIn("workspace-write", args)
        self.assertIn("--ephemeral", args)
        self.assertIn("approval_policy=\"never\"", args)

    def test_discovery_cannot_write_repository_files(self):
        args = self.run_adapter("harness_discover_cmd")
        self.assertIn("read-only", args)
        self.assertNotIn("workspace-write", args)

    def test_explain_uses_only_flags_supported_by_interactive_codex(self):
        args = self.run_explain()
        self.assertIn("read-only", args)
        self.assertIn("model-x", args)
        self.assertNotIn("--ignore-user-config", args)
        self.assertNotIn("--ignore-rules", args)


if __name__ == "__main__":
    unittest.main()
