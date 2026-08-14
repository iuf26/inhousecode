"""Tests for lib/impact.py — mines changed definitions out of a unified diff.

This feeds the AI reviewer's "does this break anything?" impact analysis, so
its value to a customer is entirely about precision: false positives bury the
real signal in noise, and a definition that goes undetected (especially one
that was *removed*, the highest-risk case) means a breaking change ships
without the reviewer ever being told to look for callers.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import load_module  # noqa: E402

impact = load_module("impact")


def diff_for(path: str, added: list[str] = (), removed: list[str] = (), context: list[str] = ()):
    lines = [
        f"diff --git a/{path} b/{path}",
        f"index 111..222 100644",
        f"--- a/{path}",
        f"+++ b/{path}",
        "@@ -1,3 +1,3 @@",
    ]
    lines += [f" {line}" for line in context]
    lines += [f"-{line}" for line in removed]
    lines += [f"+{line}" for line in added]
    return "\n".join(lines) + "\n"


class DefinitionsInTests(unittest.TestCase):
    def test_python_function_definition(self):
        self.assertIn(("function", "handle_request"), impact.definitions_in("def handle_request(req):"))

    def test_python_async_function_definition(self):
        self.assertIn(("function", "fetch_data"), impact.definitions_in("async def fetch_data():"))

    def test_python_class_definition(self):
        self.assertIn(("class", "UserService"), impact.definitions_in("class UserService(Base):"))

    def test_javascript_function_declaration(self):
        self.assertIn(("function", "computeTotal"), impact.definitions_in("export function computeTotal(items) {"))

    def test_javascript_arrow_const(self):
        self.assertIn(("function", "computeTotal"), impact.definitions_in("const computeTotal = (items) => {"))

    def test_go_function_definition(self):
        self.assertIn(("function", "HandleRequest"), impact.definitions_in("func HandleRequest(w http.ResponseWriter) {"))

    def test_go_method_with_receiver(self):
        self.assertIn(("function", "Save"), impact.definitions_in("func (s *Store) Save(item Item) error {"))

    def test_bash_function_definition(self):
        self.assertIn(("function", "resolve_python"), impact.definitions_in("resolve_python() {"))

    def test_typescript_interface(self):
        self.assertIn(("interface", "UserRecord"), impact.definitions_in("export interface UserRecord {"))

    def test_typescript_type_alias(self):
        self.assertIn(("type", "Severity"), impact.definitions_in("export type Severity = 'LOW' | 'HIGH';"))

    def test_upper_snake_constant(self):
        self.assertIn(("constant", "MAX_RETRIES"), impact.definitions_in("MAX_RETRIES = 5"))

    def test_lowercase_assignment_is_not_a_constant(self):
        # A plain variable assignment carries no contract worth reporting.
        self.assertEqual(impact.definitions_in("retries = 5"), set())

    def test_ignored_keyword_names_are_filtered(self):
        self.assertNotIn(("function", "test"), impact.definitions_in("def test():"))

    def test_short_names_are_filtered(self):
        # MIN_NAME_LENGTH is 3; "ab" is presumed noise.
        self.assertEqual(impact.definitions_in("def ab():"), set())

    def test_mention_inside_expression_is_not_a_definition(self):
        # Not anchored at line start -> not treated as a declaration.
        self.assertEqual(impact.definitions_in("    return compute_total(items)"), set())


class IsSourcePathTests(unittest.TestCase):
    def test_python_file_is_source(self):
        self.assertTrue(impact.is_source_path("src/app.py"))

    def test_markdown_is_not_source(self):
        self.assertFalse(impact.is_source_path("docs/readme.md"))

    def test_json_is_not_source(self):
        self.assertFalse(impact.is_source_path("config/settings.json"))

    def test_extensionless_file_is_treated_as_source(self):
        self.assertTrue(impact.is_source_path("bin/inhousecode"))

    def test_lockfile_is_not_source(self):
        self.assertFalse(impact.is_source_path("package.lock"))


class ParseTests(unittest.TestCase):
    def test_added_only_definition_is_classified_added(self):
        text = diff_for("src/app.py", added=["def new_handler(req):"])
        results = impact.parse(text)
        self.assertIn(("function", "added", "new_handler"), results)

    def test_removed_only_definition_is_classified_removed(self):
        text = diff_for("src/app.py", removed=["def old_handler(req):"])
        results = impact.parse(text)
        self.assertIn(("function", "removed", "old_handler"), results)

    def test_definition_on_both_sides_is_classified_modified(self):
        text = diff_for(
            "src/app.py",
            removed=["def handler(req):"],
            added=["def handler(req, ctx):"],
        )
        results = impact.parse(text)
        self.assertIn(("function", "modified", "handler"), results)

    def test_removed_definitions_sort_before_modified_and_added(self):
        text = diff_for(
            "src/app.py",
            removed=["def only_removed():", "def shared_a():"],
            added=["def only_added():", "def shared_a():"],
        )
        results = impact.parse(text)
        changes_in_order = [change for _, change, _ in results]
        first_removed_index = changes_in_order.index("removed")
        first_added_index = changes_in_order.index("added")
        self.assertLess(first_removed_index, first_added_index)

    def test_definitions_in_markdown_hunks_are_ignored(self):
        text = diff_for("docs/readme.md", added=["def not_real_code():"])
        self.assertEqual(impact.parse(text), [])

    def test_multiple_files_in_one_diff_are_both_scanned(self):
        text = diff_for("a.py", added=["def handler_a():"]) + diff_for(
            "b.py", added=["def handler_b():"]
        )
        results = impact.parse(text)
        names = {name for _, _, name in results}
        self.assertEqual({"handler_a", "handler_b"}, names)

    def test_result_count_is_capped_at_max_symbols(self):
        added = [f"def handler_{i:03d}():" for i in range(impact.MAX_SYMBOLS + 10)]
        text = diff_for("src/app.py", added=added)
        results = impact.parse(text)
        self.assertLessEqual(len(results), impact.MAX_SYMBOLS)

    def test_new_file_diff_still_mines_definitions(self):
        text = "--- /dev/null\n+++ b/src/new.py\n@@ -0,0 +1,2 @@\n+def brand_new():\n+    pass\n"
        results = impact.parse(text)
        self.assertIn(("function", "added", "brand_new"), results)

    def test_empty_diff_produces_no_results(self):
        self.assertEqual(impact.parse(""), [])


if __name__ == "__main__":
    unittest.main()
