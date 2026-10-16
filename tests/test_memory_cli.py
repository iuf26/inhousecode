"""The `inhousecode memory candidate add` CLI forwards its documented flags."""

from __future__ import annotations

import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class MemoryCandidateCliTests(unittest.TestCase):
    def test_candidate_add_forwards_source_and_evidence(self):
        # Stub memory_run so no OpenViking server is needed; we only check the
        # arguments the CLI passes to the policy layer.
        script = f"""
set -u
INHOUSECODE_HOME={ROOT!s}
REPO_ROOT={ROOT!s}
source "$INHOUSECODE_HOME/lib/common.sh"
source "$INHOUSECODE_HOME/lib/memory.sh"
memory_run() {{ printf '%s\\n' "$@"; }}
memory_candidate_add "Use the idempotency helper." \\
  --source developer-feedback --evidence payments/client.py:42
"""
        result = subprocess.run(["bash", "-c", script], text=True, capture_output=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        args = result.stdout.splitlines()
        self.assertEqual(args[0], "candidate-add")
        self.assertIn("Use the idempotency helper.", args)
        self.assertEqual(args[args.index("--source") + 1], "developer-feedback")
        self.assertEqual(args[args.index("--evidence") + 1], "payments/client.py:42")


if __name__ == "__main__":
    unittest.main()
