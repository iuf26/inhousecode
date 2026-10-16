"""Shell behavior for the opt-in default repair policy."""

from __future__ import annotations

import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def resolve_policy(*, configured: int, requested: int, no_fix: int) -> dict[str, str]:
    script = f"""
set -u
INHOUSECODE_REVIEW_FIX_BY_DEFAULT={configured}
INHOUSECODE_STATIC_AUTOFIX=0
INHOUSECODE_AI_AUTOFIX_BLOCKING=0
INHOUSECODE_AI_TRIAGE_FINDINGS=1
FIX_REQUESTED={requested}
NO_FIX={no_fix}
source {str(ROOT / 'lib' / 'fix_policy.sh')!r}
fix_policy_apply
printf 'fix_all=%s\n' "$INHOUSECODE_FIX_ALL"
printf 'requested=%s\n' "$FIX_REQUESTED"
printf 'static=%s\n' "$INHOUSECODE_STATIC_AUTOFIX"
printf 'blocking=%s\n' "$INHOUSECODE_AI_AUTOFIX_BLOCKING"
printf 'triage=%s\n' "$INHOUSECODE_AI_TRIAGE_FINDINGS"
"""
    result = subprocess.run(
        ["bash", "-c", script], text=True, capture_output=True, check=False
    )
    if result.returncode:
        raise AssertionError(result.stderr)
    return dict(line.split("=", 1) for line in result.stdout.splitlines())


class FixPolicyShellTests(unittest.TestCase):
    def test_disabled_setting_preserves_existing_repair_configuration(self):
        resolved = resolve_policy(configured=0, requested=0, no_fix=0)
        self.assertEqual(resolved["fix_all"], "0")
        self.assertEqual(resolved["static"], "0")
        self.assertEqual(resolved["blocking"], "0")
        self.assertEqual(resolved["triage"], "1")

    def test_enabled_setting_automatically_repairs_all_findings(self):
        resolved = resolve_policy(configured=1, requested=0, no_fix=0)
        self.assertEqual(resolved["fix_all"], "1")
        self.assertEqual(resolved["requested"], "1")
        self.assertEqual(resolved["static"], "1")
        self.assertEqual(resolved["blocking"], "1")
        self.assertEqual(resolved["triage"], "0")

    def test_explicit_fix_enables_the_same_policy_for_one_run(self):
        resolved = resolve_policy(configured=0, requested=1, no_fix=0)
        self.assertEqual(resolved["fix_all"], "1")
        self.assertEqual(resolved["static"], "1")

    def test_explicit_no_fix_wins_over_config_and_fix_flag(self):
        resolved = resolve_policy(configured=1, requested=1, no_fix=1)
        self.assertEqual(resolved["fix_all"], "0")
        self.assertEqual(resolved["static"], "0")
        self.assertEqual(resolved["blocking"], "0")
        self.assertEqual(resolved["triage"], "0")


if __name__ == "__main__":
    unittest.main()