"""The automatic repair loop covers advisory as well as blocking AI findings."""

from __future__ import annotations

import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class AiAutofixAllShellTests(unittest.TestCase):
    def test_fix_all_repairs_a_medium_finding_and_re_reviews(self):
        script = f"""
set -u
INHOUSECODE_HOME={str(ROOT)!r}
REPO_ROOT={str(ROOT)!r}
TARGET_MODE=worktree
INHOUSECODE_CACHE_ROOT=/tmp/inhousecode-test-fix-all
INHOUSECODE_FIX_ALL=1
INHOUSECODE_AI_MAX_FIX_LOOPS=2
AI_FINDING_MARKER='##CR-FINDING##'
AI_VERDICT_PREFIX='CODE-REVIEW'
FIX_CALLS=0
REVIEW_CALLS=0
source "$INHOUSECODE_HOME/lib/common.sh"
source "$INHOUSECODE_HOME/lib/gate_ai.sh"
AI_OUTPUT=$'##CR-FINDING##\tMEDIUM\tsrc/app.py:2\tquality\tFix it.\nCODE-REVIEW: PASS'
AI_STATUS=pass
AI_FIX_ROUNDS=0
ai_fix_round() {{ FIX_CALLS=$((FIX_CALLS + 1)); return 0; }}
ai_write_inputs() {{ return 0; }}
ai_review_once() {{
  REVIEW_CALLS=$((REVIEW_CALLS + 1))
  AI_OUTPUT='CODE-REVIEW: PASS'
  AI_STATUS=pass
}}
print_claims_report() {{ :; }}
print_findings_report() {{ :; }}
ai_autofix_all
printf 'fixes=%s reviews=%s rounds=%s\n' "$FIX_CALLS" "$REVIEW_CALLS" "$AI_FIX_ROUNDS"
"""
        result = subprocess.run(
            ["bash", "-c", script], text=True, capture_output=True, check=False
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("fixes=1 reviews=1 rounds=1", result.stdout)

    def test_fix_all_stops_after_a_round_that_makes_no_progress(self):
        script = f"""
set -u
INHOUSECODE_HOME={str(ROOT)!r}
REPO_ROOT={str(ROOT)!r}
TARGET_MODE=worktree
INHOUSECODE_CACHE_ROOT=/tmp/inhousecode-test-fix-all-stalled
INHOUSECODE_FIX_ALL=1
INHOUSECODE_AI_MAX_FIX_LOOPS=3
FIX_CALLS=0
source "$INHOUSECODE_HOME/lib/common.sh"
source "$INHOUSECODE_HOME/lib/gate_ai.sh"
AI_OUTPUT=$'##CR-FINDING##\tMEDIUM\tsrc/app.py:2\tquality\tFix it.\nCODE-REVIEW: PASS'
AI_STATUS=pass
AI_FIX_ROUNDS=0
ai_fix_round() {{ FIX_CALLS=$((FIX_CALLS + 1)); return 0; }}
ai_write_inputs() {{ return 0; }}
ai_review_once() {{ AI_STATUS=pass; return 0; }}
print_claims_report() {{ :; }}
print_findings_report() {{ :; }}
ai_autofix_all
printf 'fixes=%s rounds=%s\n' "$FIX_CALLS" "$AI_FIX_ROUNDS"
"""
        result = subprocess.run(
            ["bash", "-c", script], text=True, capture_output=True, check=False
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("fixes=1 rounds=1", result.stdout)

    def test_failed_fixer_is_still_re_reviewed_in_adversarial_mode(self):
        script = f"""
set -u
INHOUSECODE_HOME={str(ROOT)!r}
REPO_ROOT={str(ROOT)!r}
TARGET_MODE=worktree
INHOUSECODE_CACHE_ROOT=/tmp/inhousecode-test-failed-fixer-review
INHOUSECODE_FIX_ALL=1
INHOUSECODE_AI_MAX_FIX_LOOPS=2
INHOUSECODE_ADVERSARIAL_ENABLED=1
ADVERSARIAL_CALLS=0
NORMAL_CALLS=0
source "$INHOUSECODE_HOME/lib/common.sh"
source "$INHOUSECODE_HOME/lib/gate_ai.sh"
AI_OUTPUT=$'##CR-FINDING##\tMEDIUM\tsrc/app.py:2\tquality\tFix it.\nCODE-REVIEW: PASS'
AI_STATUS=pass
AI_FIX_ROUNDS=0
ai_fix_round() {{ return 1; }}
ai_write_inputs() {{ return 0; }}
ai_review_once() {{ NORMAL_CALLS=$((NORMAL_CALLS + 1)); }}
run_adversarial_review() {{
  ADVERSARIAL_CALLS=$((ADVERSARIAL_CALLS + 1))
  AI_OUTPUT='CODE-REVIEW: PASS'
  AI_STATUS=pass
}}
print_claims_report() {{ :; }}
print_findings_report() {{ :; }}
ai_autofix_all
printf 'adversarial=%s normal=%s rounds=%s\n' "$ADVERSARIAL_CALLS" "$NORMAL_CALLS" "$AI_FIX_ROUNDS"
"""
        result = subprocess.run(
            ["bash", "-c", script], text=True, capture_output=True, check=False
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("adversarial=1 normal=0 rounds=1", result.stdout)

    def test_successful_fixer_preserves_adversarial_re_review(self):
        script = f"""
set -u
INHOUSECODE_HOME={str(ROOT)!r}
REPO_ROOT={str(ROOT)!r}
TARGET_MODE=worktree
INHOUSECODE_CACHE_ROOT=/tmp/inhousecode-test-adversarial-recheck
INHOUSECODE_FIX_ALL=1
INHOUSECODE_AI_MAX_FIX_LOOPS=2
INHOUSECODE_ADVERSARIAL_ENABLED=1
ADVERSARIAL_CALLS=0
NORMAL_CALLS=0
source "$INHOUSECODE_HOME/lib/common.sh"
source "$INHOUSECODE_HOME/lib/gate_ai.sh"
AI_OUTPUT=$'##CR-FINDING##\tMEDIUM\tsrc/app.py:2\tquality\tFix it.\nCODE-REVIEW: PASS'
AI_STATUS=pass
AI_FIX_ROUNDS=0
ai_fix_round() {{ return 0; }}
ai_write_inputs() {{ return 0; }}
ai_review_once() {{ NORMAL_CALLS=$((NORMAL_CALLS + 1)); }}
run_adversarial_review() {{
  ADVERSARIAL_CALLS=$((ADVERSARIAL_CALLS + 1))
  AI_OUTPUT='CODE-REVIEW: PASS'
  AI_STATUS=pass
}}
print_claims_report() {{ :; }}
print_findings_report() {{ :; }}
ai_autofix_all
printf 'adversarial=%s normal=%s\n' "$ADVERSARIAL_CALLS" "$NORMAL_CALLS"
"""
        result = subprocess.run(
            ["bash", "-c", script], text=True, capture_output=True, check=False
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("adversarial=1 normal=0", result.stdout)


if __name__ == "__main__":
    unittest.main()