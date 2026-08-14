"""Tests for lib/static_report.py — renders the phase-1 (Semgrep) gate report.

This is the module that decides whether a commit is blocked. Two properties
matter most to a customer relying on the gate:

1. A CRITICAL/HIGH finding must always fail the build (never silently pass).
2. ``trusted_report_path`` must refuse to read a Semgrep report from outside
   the tool's own cache directory — the report path ultimately comes from a
   scan envelope, and reading an arbitrary path off it would be a traversal
   bug, not a feature.
"""

from __future__ import annotations

import contextlib
import io
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import load_module  # noqa: E402

static_report = load_module("static_report")


def semgrep_result(
    severity="ERROR",
    path="src/app.py",
    line=10,
    check_id="python.lang.security.audit.subprocess-shell-true.subprocess-shell-true",
    message="Found subprocess call with shell=True.",
    fix=None,
):
    result = {
        "check_id": check_id,
        "path": path,
        "start": {"line": line},
        "extra": {"severity": severity, "message": message},
    }
    if fix is not None:
        result["extra"]["fix"] = fix
    return result


class CleanAndControlCharTests(unittest.TestCase):
    def test_clean_collapses_whitespace_and_tabs(self):
        self.assertEqual(static_report.clean("a\tb   c\n\nd"), "a b c d")

    def test_clean_handles_none(self):
        self.assertEqual(static_report.clean(None), "")

    def test_has_control_characters_detects_low_bytes(self):
        self.assertTrue(static_report.has_control_characters("abc\x01def"))
        self.assertTrue(static_report.has_control_characters("abc\x7fdef"))
        # Tab is itself < 32, so it counts as a control character too.
        self.assertTrue(static_report.has_control_characters("abc\tdef"))
        self.assertFalse(static_report.has_control_characters("abc def"))


class SourcePathTests(unittest.TestCase):
    def test_strips_scan_target_prefix(self):
        self.assertEqual(
            static_report.source_path("/tmp/scan/src/app.py", "/tmp/scan"), "src/app.py"
        )

    def test_prefix_match_is_case_insensitive(self):
        self.assertEqual(
            static_report.source_path("/TMP/Scan/src/app.py", "/tmp/scan"), "src/app.py"
        )

    def test_normalizes_backslashes_for_windows_paths(self):
        self.assertEqual(
            static_report.source_path("C:\\scan\\src\\app.py", "C:\\scan"), "src/app.py"
        )

    def test_leaves_path_untouched_when_no_prefix_matches(self):
        self.assertEqual(static_report.source_path("src/app.py", "/other/root"), "src/app.py")


class TrustedReportPathTests(unittest.TestCase):
    def setUp(self):
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.cache_root = Path(self._tmp.name) / ".inhousecode" / "cache"
        self.cache_root.mkdir(parents=True)
        import os

        self._old_env = os.environ.get("INHOUSECODE_CACHE_ROOT")
        os.environ["INHOUSECODE_CACHE_ROOT"] = str(self.cache_root)
        self.addCleanup(self._restore_env)

    def _restore_env(self):
        import os

        if self._old_env is None:
            os.environ.pop("INHOUSECODE_CACHE_ROOT", None)
        else:
            os.environ["INHOUSECODE_CACHE_ROOT"] = self._old_env

    def test_report_inside_cache_root_is_accepted(self):
        report = self.cache_root / "run-1" / "semgrep.json"
        report.parent.mkdir(parents=True)
        report.write_text("{}")
        resolved = static_report.trusted_report_path(str(report))
        self.assertEqual(resolved, report.resolve())

    def test_report_outside_cache_root_is_rejected(self):
        # A scan envelope that points outside the tool's own cache (e.g. a
        # symlink or a doctored envelope) must never be read.
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as handle:
            handle.write(b"{}")
            outside_path = handle.name
        self.addCleanup(lambda: Path(outside_path).unlink(missing_ok=True))
        with self.assertRaisesRegex(
            static_report.ReportFormatError, "outside the scan cache root"
        ):
            static_report.trusted_report_path(outside_path)

    def test_none_sentinel_is_rejected(self):
        with self.assertRaisesRegex(static_report.ReportFormatError, "no Semgrep report path"):
            static_report.trusted_report_path("none")

    def test_control_characters_in_path_are_rejected(self):
        with self.assertRaisesRegex(
            static_report.ReportFormatError, "control characters"
        ):
            static_report.trusted_report_path(str(self.cache_root) + "/x\x01y.json")

    def test_nonexistent_path_is_rejected(self):
        with self.assertRaisesRegex(
            static_report.ReportFormatError, "could not resolve"
        ):
            static_report.trusted_report_path(str(self.cache_root / "missing.json"))


class ValidateReportTests(unittest.TestCase):
    def test_requires_results_and_errors_arrays(self):
        with self.assertRaisesRegex(
            static_report.ReportFormatError, "requires results and errors"
        ):
            static_report.validate_report({"results": []})

    def test_scan_errors_are_a_hard_failure(self):
        with self.assertRaisesRegex(static_report.ReportFormatError, "scan errors"):
            static_report.validate_report({"results": [], "errors": ["boom"]})

    def test_invalid_severity_is_rejected(self):
        report = {"results": [semgrep_result(severity="NOPE")], "errors": []}
        with self.assertRaisesRegex(static_report.ReportFormatError, "invalid severity"):
            static_report.validate_report(report)

    def test_missing_path_is_rejected(self):
        result = semgrep_result()
        del result["path"]
        with self.assertRaisesRegex(static_report.ReportFormatError, "invalid path"):
            static_report.validate_report({"results": [result], "errors": []})

    def test_non_positive_line_is_rejected(self):
        result = semgrep_result(line=0)
        with self.assertRaisesRegex(static_report.ReportFormatError, "invalid start.line"):
            static_report.validate_report({"results": [result], "errors": []})

    def test_missing_check_id_is_rejected(self):
        result = semgrep_result(check_id="   ")
        with self.assertRaisesRegex(static_report.ReportFormatError, "no check_id"):
            static_report.validate_report({"results": [result], "errors": []})

    def test_valid_result_passes_through(self):
        report = {"results": [semgrep_result()], "errors": []}
        validated = static_report.validate_report(report)
        self.assertEqual(len(validated), 1)


class ShortRuleAndFixTests(unittest.TestCase):
    def test_short_rule_takes_last_dotted_segment(self):
        self.assertEqual(
            static_report.short_rule("python.lang.security.audit.subprocess-shell-true"),
            "subprocess-shell-true",
        )

    def test_short_rule_handles_bare_id(self):
        self.assertEqual(static_report.short_rule("no-dots-here"), "no-dots-here")

    def test_short_fix_keeps_first_sentence(self):
        self.assertEqual(
            static_report.short_fix("Do the thing. Then do another thing."),
            "Do the thing.",
        )

    def test_short_fix_truncates_long_text_with_ellipsis(self):
        text = "x" * 200
        result = static_report.short_fix(text, limit=10)
        self.assertEqual(len(result), 10)
        self.assertTrue(result.endswith("\u2026"))


class BuildFindingsTests(unittest.TestCase):
    def test_maps_semgrep_severity_to_gate_severity(self):
        results = [
            semgrep_result(severity="ERROR"),
            semgrep_result(severity="WARNING"),
            semgrep_result(severity="INFO"),
        ]
        findings = static_report.build_findings(results, "")
        severities = [item[0] for item in findings]
        self.assertEqual(set(severities), {"CRITICAL", "MEDIUM", "LOW"})

    def test_sorts_by_severity_critical_first(self):
        results = [
            semgrep_result(severity="INFO", path="a.py"),
            semgrep_result(severity="ERROR", path="b.py"),
            semgrep_result(severity="WARNING", path="c.py"),
        ]
        findings = static_report.build_findings(results, "")
        self.assertEqual([f[0] for f in findings], ["CRITICAL", "MEDIUM", "LOW"])

    def test_falls_back_to_message_when_fix_is_placeholder(self):
        result = semgrep_result(fix="none", message="Use a safer API.")
        findings = static_report.build_findings([result], "")
        self.assertEqual(findings[0][3], "Use a safer API.")

    def test_falls_back_to_message_when_fix_is_blank(self):
        result = semgrep_result(fix="   ", message="Use a safer API.")
        findings = static_report.build_findings([result], "")
        self.assertEqual(findings[0][3], "Use a safer API.")

    def test_uses_fix_when_present_and_meaningful(self):
        result = semgrep_result(fix="Replace shell=True with a list of args.")
        findings = static_report.build_findings([result], "")
        self.assertEqual(findings[0][3], "Replace shell=True with a list of args.")

    def test_strips_scan_target_from_location(self):
        result = semgrep_result(path="/scan/src/app.py", line=42)
        findings = static_report.build_findings([result], "/scan")
        self.assertEqual(findings[0][1], "src/app.py:42")


class PrintFindingsTests(unittest.TestCase):
    def _capture(self, findings):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            exit_code = static_report.print_findings(findings)
        return exit_code, buf.getvalue()

    def test_no_findings_passes(self):
        exit_code, out = self._capture([])
        self.assertEqual(exit_code, static_report.EXIT_PASS)
        self.assertIn("STATIC-CHECK: PASS", out)

    def test_critical_finding_blocks(self):
        exit_code, out = self._capture([("CRITICAL", "a.py:1", "rule", "fix it")])
        self.assertEqual(exit_code, static_report.EXIT_BLOCKING)
        self.assertIn("STATIC-CHECK: FAIL", out)
        self.assertIn("##STATIC-FINDING##\tCRITICAL\ta.py:1\trule\tfix it", out)

    def test_only_low_findings_still_passes(self):
        # LOW/MEDIUM are advisory-only; only CRITICAL/HIGH should ever block.
        exit_code, out = self._capture([("LOW", "a.py:1", "rule", "note")])
        self.assertEqual(exit_code, static_report.EXIT_PASS)
        self.assertIn("STATIC-CHECK: PASS", out)


class PrintReportTests(unittest.TestCase):
    def _capture(self, scan):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            exit_code = static_report.print_report(scan)
        return exit_code, buf.getvalue()

    def test_skipped_scan_passes(self):
        exit_code, out = self._capture({"scan_status": "skipped", "scan_reason": "no source files"})
        self.assertEqual(exit_code, static_report.EXIT_PASS)
        self.assertIn("STATIC-CHECK: PASS", out)

    def test_unavailable_scan_fails_closed(self):
        # If the scanner could not run at all, the gate must not silently
        # pass the commit through.
        exit_code, out = self._capture({"scan_status": "unavailable", "scan_reason": "semgrep not found"})
        self.assertEqual(exit_code, static_report.EXIT_UNAVAILABLE)
        self.assertIn("STATIC-CHECK: FAIL", out)


class EndToEndTests(unittest.TestCase):
    """Exercises the full completed-scan path through a real cache root."""

    def setUp(self):
        import os
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.cache_root = Path(self._tmp.name) / ".inhousecode" / "cache"
        self.cache_root.mkdir(parents=True)
        self._old_env = os.environ.get("INHOUSECODE_CACHE_ROOT")
        os.environ["INHOUSECODE_CACHE_ROOT"] = str(self.cache_root)
        self.addCleanup(self._restore_env)

    def _restore_env(self):
        import os

        if self._old_env is None:
            os.environ.pop("INHOUSECODE_CACHE_ROOT", None)
        else:
            os.environ["INHOUSECODE_CACHE_ROOT"] = self._old_env

    def test_completed_scan_with_blocking_finding_fails_the_gate(self):
        report_path = self.cache_root / "semgrep.json"
        report_path.write_text(
            json.dumps({"results": [semgrep_result(severity="ERROR")], "errors": []})
        )
        scan = {
            "scan_status": "completed",
            "semgrep_json": str(report_path),
            "scan_target": "",
        }
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            exit_code = static_report.print_report(scan)
        self.assertEqual(exit_code, static_report.EXIT_BLOCKING)
        self.assertIn("##STATIC-FINDING##\tCRITICAL", buf.getvalue())
        self.assertIn("STATIC-CHECK: FAIL", buf.getvalue())

    def test_completed_scan_with_no_results_passes(self):
        report_path = self.cache_root / "semgrep.json"
        report_path.write_text(json.dumps({"results": [], "errors": []}))
        scan = {"scan_status": "completed", "semgrep_json": str(report_path), "scan_target": ""}
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            exit_code = static_report.print_report(scan)
        self.assertEqual(exit_code, static_report.EXIT_PASS)
        self.assertIn("STATIC-CHECK: PASS", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
