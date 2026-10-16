"""The same frozen memory context must reach every reviewer role."""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class MemoryPromptIntegrationTests(unittest.TestCase):
    def test_normal_critic_lens_and_synthesis_receive_same_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)
            (cache / "scan-files.txt").write_text("app.py\n", encoding="utf-8")
            (cache / "findings.txt").write_text(
                "##CR-FINDING##\tHIGH\tapp.py:1\tretry\tBound retries.\n",
                encoding="utf-8",
            )
            script = f"""
set -u
INHOUSECODE_HOME={ROOT!s}
REPO_ROOT={ROOT!s}
INHOUSECODE_CACHE_ROOT={cache!s}
INHOUSECODE_MEMORY_ENABLED=1
TARGET_MODE=path
TARGET_PATH=app.py
AI_DIFF_PATH=
AI_SOURCE_ROOT={ROOT!s}
AI_INTENT_PATH=
AI_COMMITS_PATH=
AI_IMPACT_PATH=
AI_FINDING_MARKER='##CR-FINDING##'
AI_MISDECL_MARKER='##CR-MISDECL##'
AI_VERDICT_PREFIX='CODE-REVIEW'
AI_OUTPUT=$'##CR-FINDING##\tHIGH\tapp.py:1\tretry\tBound retries.\nCODE-REVIEW: FAIL'
AI_MEMORY_STATUS=available
AI_MEMORY_SNAPSHOT_HASH=frozen-hash-123
AI_MEMORY_CONTEXT='MEMORY-SENTINEL-ONE-SNAPSHOT'
source "$INHOUSECODE_HOME/lib/common.sh"
source "$INHOUSECODE_HOME/lib/memory.sh"
source "$INHOUSECODE_HOME/lib/gate_ai.sh"
source "$INHOUSECODE_HOME/lib/gate_adversarial.sh"
ai_build_prompt
printf '%s\n' '---NORMAL---' "$AI_PROMPT"
printf '%s\n' '---CRITIC---'
ai_critique_prompt
printf '%s\n' '---LENS---'
adversarial_lens_prompt skeptic
printf '%s\n' '---SYNTHESIS---'
adversarial_synthesis_prompt "$INHOUSECODE_CACHE_ROOT/findings.txt"
"""
            result = subprocess.run(
                ["bash", "-c", script],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.count("MEMORY-SENTINEL-ONE-SNAPSHOT"), 4)
            self.assertEqual(result.stdout.count("frozen-hash-123"), 4)
            self.assertIn("Unverified candidate evidence", result.stdout)
            self.assertNotIn("rulebook", result.stdout.lower())
            self.assertIn(
                "not a function declaration, blank line, comment, or nearby context",
                result.stdout,
            )


if __name__ == "__main__":
    unittest.main()
