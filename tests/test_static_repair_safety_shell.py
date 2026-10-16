"""Static repair policy and failed-fixer safety contracts."""

from __future__ import annotations

import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run_static(*, fix_all: str, fix_rc: int) -> subprocess.CompletedProcess[str]:
    script = f"""
set -u
INHOUSECODE_HOME={str(ROOT)!r}
REPO_ROOT={str(ROOT)!r}
INHOUSECODE_CACHE_ROOT=/tmp/inhousecode-test-static-repair
TARGET_MODE=worktree
INHOUSECODE_STATIC_ENABLED=1
INHOUSECODE_STATIC_FIX_SEVERITY=blocking
INHOUSECODE_STATIC_AUTOFIX=1
INHOUSECODE_STATIC_MAX_FIX_LOOPS=2
INHOUSECODE_FIX_ALL={fix_all}
STATIC_FIX_ROUNDS=0
SCANS=0
SELECTION=''
mkdir -p "$INHOUSECODE_CACHE_ROOT"
source "$INHOUSECODE_HOME/lib/common.sh"
source "$INHOUSECODE_HOME/lib/gate_static.sh"
static_scan_once() {{
  SCANS=$((SCANS + 1))
  printf '{{}}' > "$INHOUSECODE_CACHE_ROOT/scan-envelope.json"
  return 0
}}
static_classify() {{
  if [ "$SCANS" -eq 1 ]; then
    STATIC_OUTPUT="$(printf '##STATIC-FINDING##\tMEDIUM\tsrc/app.py:2\tquality\tFix it.\nSTATIC-CHECK: PASS\n')"
  else
    STATIC_OUTPUT='STATIC-CHECK: PASS'
  fi
  STATIC_STATUS=pass
}}
static_fix_round() {{ SELECTION="$1"; return {fix_rc}; }}
static_restage() {{ return 0; }}
print_findings_report() {{ :; }}
run_static_gate
printf 'scans=%s selection=%s rounds=%s\n' "$SCANS" "$SELECTION" "$STATIC_FIX_ROUNDS"
"""
    return subprocess.run(
        ["bash", "-c", script], text=True, capture_output=True, check=False
    )


class StaticRepairSafetyShellTests(unittest.TestCase):
    def test_fix_all_overrides_blocking_static_severity(self):
        result = run_static(fix_all="1", fix_rc=0)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("scans=2 selection=all rounds=1", result.stdout)

    def test_failed_fixer_is_still_rescanned(self):
        result = run_static(fix_all="1", fix_rc=1)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("scans=2 selection=all rounds=1", result.stdout)


if __name__ == "__main__":
    unittest.main()