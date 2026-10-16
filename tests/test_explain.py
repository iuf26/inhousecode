"""Tests for lib/explain.py — builds the human-readable "explain" briefing.

This is the deterministic half of `inhousecode explain`: it takes a raw gate
finding and turns it into something a developer trusts, by quoting their
team's own rulebook verbatim rather than paraphrasing it. The two properties
that matter to a customer: (1) a finding is only ever matched to the rule the
reviewer actually cited, not a coincidentally similar one, and (2) a source
excerpt is never fabricated or shown out of bounds.
"""

from __future__ import annotations

import argparse
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import load_module  # noqa: E402

explain = load_module("explain")


def make_args(**overrides):
    defaults = dict(
        findings="",
        out="",
        repo_root=".",
        rulebook="",
        rulebook_path="",
        target_mode="staged",
        diff_head="HEAD",
        diff_source="commit",
        context=5,
    )
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


class FindingTests(unittest.TestCase):
    def test_parses_path_and_line_from_location(self):
        finding = explain.Finding("static", "CRITICAL", "src/app.py:42", "rule-id", "fix it")
        self.assertEqual(finding.path, "src/app.py")
        self.assertEqual(finding.line, 42)

    def test_normalizes_windows_path_separators(self):
        finding = explain.Finding("static", "CRITICAL", "src\\app.py:42", "rule-id", "fix it")
        self.assertEqual(finding.path, "src/app.py")

    def test_malformed_location_leaves_path_and_line_empty(self):
        finding = explain.Finding("static", "CRITICAL", "not-a-location", "rule-id", "fix it")
        self.assertEqual(finding.path, "")
        self.assertEqual(finding.line, 0)

    def test_blocking_true_for_critical_and_high(self):
        self.assertTrue(explain.Finding("static", "CRITICAL", "a:1", "x", "y").blocking)
        self.assertTrue(explain.Finding("static", "HIGH", "a:1", "x", "y").blocking)

    def test_blocking_false_for_medium_and_low(self):
        self.assertFalse(explain.Finding("static", "MEDIUM", "a:1", "x", "y").blocking)
        self.assertFalse(explain.Finding("static", "LOW", "a:1", "x", "y").blocking)


class ReadFindingsTests(unittest.TestCase):
    def _write(self, content: str) -> Path:
        import tempfile

        handle = tempfile.NamedTemporaryFile(mode="w", suffix=".tsv", delete=False, encoding="utf-8")
        handle.write(content)
        handle.close()
        self.addCleanup(lambda: Path(handle.name).unlink(missing_ok=True))
        return Path(handle.name)

    def test_parses_well_formed_rows(self):
        path = self._write("static\tCRITICAL\ta.py:1\trule-a\tfix a\n")
        findings = explain.read_findings(path)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].category, "rule-a")

    def test_skips_rows_with_wrong_field_count(self):
        path = self._write("static\tCRITICAL\ta.py:1\trule-a\n")  # only 4 fields
        self.assertEqual(explain.read_findings(path), [])

    def test_skips_blank_lines(self):
        path = self._write("\n\nstatic\tLOW\ta.py:1\trule-a\tfix a\n")
        self.assertEqual(len(explain.read_findings(path)), 1)

    def test_sorts_by_severity_rank_critical_first(self):
        path = self._write(
            "static\tLOW\ta.py:1\tr1\tfix\n" "static\tCRITICAL\tb.py:2\tr2\tfix\n"
        )
        findings = explain.read_findings(path)
        self.assertEqual([f.severity for f in findings], ["CRITICAL", "LOW"])

    def test_missing_file_returns_empty_list(self):
        self.assertEqual(explain.read_findings(Path("/nonexistent/findings.tsv")), [])



class BuildExcerptTests(unittest.TestCase):
    def test_window_is_clamped_to_file_bounds(self):
        lines = [f"line{i}" for i in range(1, 6)]  # 5 lines
        finding = explain.Finding("static", "LOW", "a.py:1", "x", "y")
        excerpt = explain.build_excerpt(finding, lines, context=5)
        # Should not attempt to render line 0 or negative line numbers.
        self.assertEqual(len(excerpt), 5)
        self.assertTrue(excerpt[0].startswith(">"))

    def test_marker_is_on_the_finding_line(self):
        lines = [f"line{i}" for i in range(1, 11)]
        finding = explain.Finding("static", "LOW", "a.py:5", "x", "y")
        excerpt = explain.build_excerpt(finding, lines, context=2)
        marked = [row for row in excerpt if row.startswith(">")]
        self.assertEqual(len(marked), 1)
        self.assertIn("line5", marked[0])

    def test_line_number_beyond_file_length_returns_empty(self):
        lines = ["only one line"]
        finding = explain.Finding("static", "LOW", "a.py:99", "x", "y")
        self.assertEqual(explain.build_excerpt(finding, lines, context=5), [])

    def test_no_lines_available_returns_empty(self):
        finding = explain.Finding("static", "LOW", "a.py:1", "x", "y")
        self.assertEqual(explain.build_excerpt(finding, None, context=5), [])


class ReadSourceFallbackTests(unittest.TestCase):
    def test_falls_back_to_disk_read_outside_staged_or_diff_modes(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            (repo_root / "app.py").write_text("print('hi')\n")
            finding = explain.Finding("static", "LOW", "app.py:1", "x", "y")
            args = make_args(repo_root=str(repo_root), target_mode="working-tree")
            lines = explain.read_source(finding, args)
            self.assertEqual(lines, ["print('hi')"])

    def test_missing_file_on_disk_returns_none(self):
        finding = explain.Finding("static", "LOW", "missing.py:1", "x", "y")
        args = make_args(repo_root="/nonexistent/repo", target_mode="working-tree")
        self.assertIsNone(explain.read_source(finding, args))

    def test_finding_without_a_path_returns_none(self):
        finding = explain.Finding("static", "LOW", "not-a-location", "x", "y")
        args = make_args(target_mode="working-tree")
        self.assertIsNone(explain.read_source(finding, args))

    def test_absolute_path_outside_repo_is_rejected(self):
        import tempfile

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False
        ) as secret:
            secret.write("outside the repo\n")
            secret_path = secret.name
        try:
            with tempfile.TemporaryDirectory() as tmp:
                finding = explain.Finding("static", "LOW", f"{secret_path}:1", "x", "y")
                args = make_args(repo_root=tmp, target_mode="working-tree")
                self.assertIsNone(explain.read_source(finding, args))
        finally:
            os.unlink(secret_path)

    def test_parent_traversal_path_is_rejected(self):
        import tempfile

        with tempfile.TemporaryDirectory() as outer:
            (Path(outer) / "secret.txt").write_text("outside the repo\n")
            repo_root = Path(outer) / "repo"
            repo_root.mkdir()
            finding = explain.Finding(
                "static", "LOW", "../secret.txt:1", "x", "y"
            )
            args = make_args(repo_root=str(repo_root), target_mode="working-tree")
            self.assertIsNone(explain.read_source(finding, args))


class RenderTests(unittest.TestCase):
    def test_render_quotes_promoted_project_rule_and_scope(self):
        findings = [
            explain.Finding(
                "review", "MEDIUM", "a.py:2", "project-select-columns", "name columns"
            )
        ]
        rules = {
            "project-select-columns": {
                "scope": "project",
                "content": "Queries must name their columns; SELECT * is not allowed.",
                "uri": "viking://project/rule.json",
            }
        }
        out = explain.render(findings, rules, make_args())
        self.assertIn("Rule source: promoted project knowledge", out)
        self.assertIn("Rule: Queries must name their columns; SELECT * is not allowed.", out)
        self.assertIn("Memory record: `project-select-columns`", out)

    def test_parse_memory_rules_reads_project_and_global_sections(self):
        context = """## Promoted project knowledge
- [project-one] Project rule.
  URI: viking://project/one.json; status: promoted; repository: repo; confidence: high

## Promoted global knowledge
- [global-one] Global rule.
  URI: viking://global/one.json; status: promoted; repository: global; confidence: high
"""
        rules = explain.parse_memory_rules(context)
        self.assertEqual(rules["project-one"]["scope"], "project")
        self.assertEqual(rules["project-one"]["content"], "Project rule.")
        self.assertEqual(rules["global-one"]["scope"], "global")

    def test_render_includes_counts_and_gate_label(self):
        findings = [explain.Finding("static", "CRITICAL", "a.py:1", "no-broad-except", "catch specific errors")]
        args = make_args()
        out = explain.render(findings, {}, args)
        self.assertIn("1 finding(s) to explain - 1 blocking, 0 advisory.", out)
        self.assertIn("Semgrep (phase 1)", out)

    def test_render_reports_review_category(self):
        findings = [explain.Finding("review", "MEDIUM", "a.py:1", "unmatched-category", "fix it")]
        out = explain.render(findings, {}, make_args())
        self.assertIn("Review category `unmatched-category`", out)
        self.assertNotIn("rulebook", out.lower())

    def test_render_reports_semgrep_rule_when_static_gate_unmatched(self):
        findings = [explain.Finding("static", "MEDIUM", "a.py:1", "some-semgrep-rule", "fix it")]
        out = explain.render(findings, {}, make_args())
        self.assertIn("Semgrep rule `some-semgrep-rule`", out)

    def test_render_notes_missing_source_excerpt(self):
        findings = [explain.Finding("static", "LOW", "missing.py:1", "x", "y")]
        args = make_args(repo_root="/nonexistent/repo", target_mode="working-tree")
        out = explain.render(findings, {}, args)
        self.assertIn("Source excerpt unavailable for `missing.py:1`.", out)


if __name__ == "__main__":
    unittest.main()
