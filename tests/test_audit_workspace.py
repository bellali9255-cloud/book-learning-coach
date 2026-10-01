import copy
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from tests import schema_compat


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "assets" / "progress.schema.json"
FIXTURE_DIR = ROOT / "tests" / "fixtures" / "sample-book"
COMPAT = types.SimpleNamespace(
    Draft202012Validator=schema_compat.Draft202012Validator,
    ValidationError=schema_compat.ValidationError,
)


class WorkspaceAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "source").mkdir()
        (self.root / "learning").mkdir()
        (self.root / "notes").mkdir()
        shutil.copy2(FIXTURE_DIR / "source.md", self.root / "source" / "source.md")
        (self.root / "source" / "original.txt").write_text(
            "合成示例书原始内容。\n", encoding="utf-8"
        )
        shutil.copy2(FIXTURE_DIR / "minimal-progress.json", self.root / "learning" / "progress.json")
        (self.root / "notes" / "reading-notes.md").write_text(
            "# 笔记\n\n"
            "<!-- blc:start note_1234abcd -->\n"
            "chapter_id: ch_a14e90b2\n"
            "source_block_id: src_91ac73e2\n"
            "## 第一章笔记\n合成笔记。\n"
            "<!-- blc:end note_1234abcd -->\n",
            encoding="utf-8",
        )
        state = self.read_state()
        state["source"]["original_sha256"] = self._sha256(self.root / "source" / "original.txt")
        state["source"]["canonical_sha256"] = self._sha256(self.root / "source" / "source.md")
        lesson = state["lessons"]["lesson_83d712fa"]
        lesson["source_hashes"] = {
            "original_sha256": state["source"]["original_sha256"],
            "canonical_sha256": state["source"]["canonical_sha256"],
        }
        state["review_cards"]["review_6ea7b190"]["source_hashes"] = copy.deepcopy(
            lesson["source_hashes"]
        )
        self.write_state(state)
        self.validator_patch = patch("scripts.progress._import_jsonschema", return_value=COMPAT)
        self.validator_patch.start()
        self.addCleanup(self.validator_patch.stop)

    def read_state(self):
        return json.loads((self.root / "learning" / "progress.json").read_text(encoding="utf-8"))

    def write_state(self, state):
        (self.root / "learning" / "progress.json").write_text(
            json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def mark_first_chapter_audited(self):
        state = self.read_state()
        chapter_id = "ch_a14e90b2"
        state["chapters"][chapter_id]["deep_read_status"] = "audited"
        state["audit"]["chapters"][chapter_id] = {
            "status": "audited",
            "audited_at": "2026-10-01T16:00:00+08:00",
            "issues": [],
        }
        state["audit"]["book_status"] = "incomplete"
        self.write_state(state)

    def test_canonical_source_must_be_unique(self):
        from scripts.audit_workspace import audit_workspace

        duplicate = self.root / "archive" / "source"
        duplicate.mkdir(parents=True)
        shutil.copy2(self.root / "source" / "source.md", duplicate / "source.md")
        report = audit_workspace(self.root)
        self.assertTrue(any("canonical" in error and "exactly one" in error for error in report["hard_errors"]))

    def test_source_block_refs_must_resolve_to_canonical_source(self):
        from scripts.audit_workspace import audit_workspace

        (self.root / "notes" / "reading-notes.md").write_text(
            "source_block_id: src_deadbeef\n", encoding="utf-8"
        )
        report = audit_workspace(self.root)
        self.assertTrue(any("src_deadbeef" in error for error in report["hard_errors"]))

    def test_source_files_and_hashes_must_match_progress(self):
        from scripts.audit_workspace import audit_workspace

        (self.root / "source" / "source.md").write_text("被篡改", encoding="utf-8")
        mismatch = audit_workspace(self.root)
        self.assertTrue(any("canonical_sha256" in error for error in mismatch["hard_errors"]))

        shutil.copy2(FIXTURE_DIR / "source.md", self.root / "source" / "source.md")
        state = self.read_state()
        state["source"]["canonical_sha256"] = self._sha256(self.root / "source" / "source.md")
        state["lessons"]["lesson_83d712fa"]["source_hashes"]["canonical_sha256"] = state["source"]["canonical_sha256"]
        state["review_cards"]["review_6ea7b190"]["source_hashes"]["canonical_sha256"] = state["source"]["canonical_sha256"]
        self.write_state(state)
        (self.root / "source" / "original.txt").unlink()
        missing = audit_workspace(self.root)
        self.assertTrue(any("original" in error and "missing" in error for error in missing["hard_errors"]))

    def test_progress_and_reading_notes_must_each_be_unique(self):
        from scripts.audit_workspace import audit_workspace

        extra = self.root / "archive"
        extra.mkdir()
        shutil.copy2(self.root / "learning" / "progress.json", extra / "progress.json")
        shutil.copy2(self.root / "notes" / "reading-notes.md", extra / "reading-notes.md")
        report = audit_workspace(self.root)
        self.assertTrue(any("exactly one progress.json" in error for error in report["hard_errors"]))
        self.assertTrue(any("exactly one canonical reading-notes.md" in error for error in report["hard_errors"]))

    def test_chapter_audit_authorizes_only_chapter_scoped_assets(self):
        from scripts.audit_workspace import audit_chapter, audit_workspace, can_emit_asset

        self.mark_first_chapter_audited()
        chapter = audit_chapter(self.root, "ch_a14e90b2")
        whole = audit_workspace(self.root)
        self.assertTrue(can_emit_asset(chapter, "chapter", "ch_a14e90b2"))
        self.assertFalse(can_emit_asset(whole, "book", None))

    def test_chapter_audit_requires_canonical_structured_notes(self):
        from scripts.audit_workspace import audit_chapter, can_emit_asset

        self.mark_first_chapter_audited()
        (self.root / "notes" / "reading-notes.md").unlink()
        missing = audit_chapter(self.root, "ch_a14e90b2")
        self.assertFalse(can_emit_asset(missing, "chapter", "ch_a14e90b2"))
        self.assertTrue(any("reading-notes" in error for error in missing["hard_errors"]))

        (self.root / "notes" / "reading-notes.md").write_text(
            "<!-- blc:start note_1234abcd -->\n未闭合\n", encoding="utf-8"
        )
        malformed = audit_chapter(self.root, "ch_a14e90b2")
        self.assertFalse(can_emit_asset(malformed, "chapter", "ch_a14e90b2"))
        self.assertTrue(any("marker" in error for error in malformed["hard_errors"]))

    def test_book_audit_denied_when_any_included_chapter_is_incomplete(self):
        from scripts.audit_workspace import audit_book, can_emit_asset

        self.mark_first_chapter_audited()
        state = self.read_state()
        second = "ch_22222222"
        state["chapters"][second] = {
            "chapter_id": second,
            "title": "第二章",
            "display_order": 2,
            "browse_status": "mapped",
            "deep_read_status": "partial",
            "source_block_ids": ["src_22222222"],
        }
        state["reading_scope"]["included_chapter_ids"].append(second)
        state["audit"]["chapters"][second] = {"status": "in_progress", "audited_at": None, "issues": []}
        self.write_state(state)
        (self.root / "source" / "source.md").write_text(
            (self.root / "source" / "source.md").read_text(encoding="utf-8")
            + "\n<a id=\"src_22222222\"></a>\n## 第二章\n",
            encoding="utf-8",
        )
        report = audit_book(self.root)
        self.assertFalse(can_emit_asset(report, "book", None))
        self.assertTrue(any(second in error for error in report["hard_errors"]))

    def test_exclusions_require_reasons_and_unclassified_chapters_fail(self):
        from scripts.audit_workspace import audit_workspace

        state = self.read_state()
        state["reading_scope"]["included_chapter_ids"] = []
        state["reading_scope"]["excluded_chapter_ids"] = ["ch_a14e90b2"]
        report = audit_workspace(self.root) if self._write_then_true(state) else None
        self.assertTrue(any("reason" in error for error in report["hard_errors"]))

        state = self.read_state()
        state["reading_scope"]["included_chapter_ids"] = []
        state["reading_scope"]["excluded_chapter_ids"] = []
        report = audit_workspace(self.root) if self._write_then_true(state) else None
        self.assertTrue(any("classify" in error for error in report["hard_errors"]))

    def test_duplicate_stable_ids_are_hard_errors(self):
        from scripts.audit_workspace import audit_workspace

        (self.root / "notes" / "reading-notes.md").write_text(
            "<!-- blc:start note_1234abcd -->\n一\n<!-- blc:end note_1234abcd -->\n"
            "<!-- blc:start note_1234abcd -->\n二\n<!-- blc:end note_1234abcd -->\n",
            encoding="utf-8",
        )
        report = audit_workspace(self.root)
        self.assertTrue(any("duplicate stable ID" in error for error in report["hard_errors"]))

    def test_all_managed_markdown_assets_require_valid_markers_and_prefixes(self):
        from scripts.audit_workspace import audit_workspace

        toolkit = self.root / "toolkit"
        toolkit.mkdir()
        path = toolkit / "method-cards.md"
        path.write_text("<!-- blc:start method_1234abcd -->\n未闭合\n", encoding="utf-8")
        malformed = audit_workspace(self.root)
        self.assertTrue(any("method-cards.md" in error and "marker" in error for error in malformed["hard_errors"]))

        path.write_text(
            "<!-- blc:start scene_1234abcd -->\n错误前缀\n<!-- blc:end scene_1234abcd -->\n",
            encoding="utf-8",
        )
        wrong_prefix = audit_workspace(self.root)
        self.assertTrue(any("method-cards.md" in error and "method_" in error for error in wrong_prefix["hard_errors"]))

    def test_cache_is_never_a_backlink_target(self):
        from scripts.audit_workspace import audit_workspace

        (self.root / ".cache").mkdir()
        (self.root / ".cache" / "candidate.md").write_text(
            '<a id="src_deadbeef"></a>\n缓存候选', encoding="utf-8"
        )
        (self.root / "notes" / "reading-notes.md").write_text(
            "source_block_id: src_deadbeef\n", encoding="utf-8"
        )
        report = audit_workspace(self.root)
        self.assertTrue(any(".cache" in error and "src_deadbeef" in error for error in report["hard_errors"]))

    def _write_then_true(self, state):
        self.write_state(state)
        return True

    @staticmethod
    def _sha256(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def test_audit_script_has_a_working_direct_cli(self):
        completed = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "audit_workspace.py"), "--help"],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("scope", completed.stdout.lower())


if __name__ == "__main__":
    unittest.main()
