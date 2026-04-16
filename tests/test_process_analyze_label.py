from __future__ import annotations

import unittest

from src.analyze_issue import ANALYSIS_MARKER, is_analysis_comment, normalize_analysis_markdown
from src.process_analyze_label import merge_labels


class ProcessAnalyzeLabelTests(unittest.TestCase):
    def test_merge_labels_adds_processed_and_removes_trigger(self) -> None:
        merged = merge_labels(["bug", "analyze"], ["analyzed"], ["analyze"])
        self.assertEqual(merged, ["bug", "analyzed"])

    def test_normalize_analysis_markdown_prepends_marker_once(self) -> None:
        normalized = normalize_analysis_markdown("> header")
        self.assertTrue(normalized.startswith(ANALYSIS_MARKER))
        self.assertEqual(normalize_analysis_markdown(normalized), normalized)

    def test_is_analysis_comment_accepts_marker_or_header(self) -> None:
        self.assertTrue(is_analysis_comment(f"{ANALYSIS_MARKER}\nhello"))
        self.assertTrue(is_analysis_comment("> 🤖 **/issue-analysis by Ollama (gemma4:26b)**"))
        self.assertFalse(is_analysis_comment("plain comment"))


if __name__ == "__main__":
    unittest.main()
