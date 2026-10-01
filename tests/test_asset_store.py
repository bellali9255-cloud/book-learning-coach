import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class AssetStoreTests(unittest.TestCase):
    def test_create_and_update_same_id_without_duplication(self):
        from scripts.asset_store import upsert_block

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "method-cards.md"
            upsert_block(path, "method_1234abcd", "# 方法一\n\n旧内容")
            upsert_block(path, "method_1234abcd", "# 方法一\n\n新内容")
            text = path.read_text(encoding="utf-8")
            self.assertEqual(text.count("<!-- blc:start method_1234abcd -->"), 1)
            self.assertNotIn("旧内容", text)
            self.assertIn("新内容", text)

    def test_replace_requires_existing_block(self):
        from scripts.asset_store import replace_block

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "notes.md"
            with self.assertRaises(KeyError):
                replace_block(path, "note_1234abcd", "内容")

    def test_dedupe_keeps_last_complete_occurrence(self):
        from scripts.asset_store import dedupe_blocks

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "notes.md"
            path.write_text(
                "前言\n\n"
                "<!-- blc:start note_1234abcd -->\n旧\n<!-- blc:end note_1234abcd -->\n\n"
                "<!-- blc:start note_1234abcd -->\n新\n<!-- blc:end note_1234abcd -->\n",
                encoding="utf-8",
            )
            self.assertEqual(dedupe_blocks(path), ["note_1234abcd"])
            text = path.read_text(encoding="utf-8")
            self.assertEqual(text.count("blc:start note_1234abcd"), 1)
            self.assertNotIn("旧", text)
            self.assertIn("新", text)

    def test_malformed_or_nested_markers_are_refused(self):
        from scripts.asset_store import upsert_block

        samples = [
            "<!-- blc:start note_1234abcd -->\n没有结尾\n",
            "<!-- blc:start note_1234abcd -->\n<!-- blc:start note_22222222 -->\n<!-- blc:end note_22222222 -->\n<!-- blc:end note_1234abcd -->\n",
            "<!-- blc:start note_1234abcd -->\n<!-- blc:end note_22222222 -->\n",
        ]
        for sample in samples:
            with self.subTest(sample=sample), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "notes.md"
                path.write_text(sample, encoding="utf-8")
                before = path.read_bytes()
                with self.assertRaises(ValueError):
                    upsert_block(path, "note_33333333", "内容")
                self.assertEqual(path.read_bytes(), before)

    def test_atomic_replace_failure_preserves_asset(self):
        from scripts.asset_store import upsert_block

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "notes.md"
            upsert_block(path, "note_1234abcd", "原始")
            before = path.read_bytes()
            with patch("scripts.asset_store.os.replace", side_effect=OSError("simulated replace failure")):
                with self.assertRaisesRegex(OSError, "replace failure"):
                    upsert_block(path, "note_1234abcd", "更新")
            self.assertEqual(path.read_bytes(), before)

    def test_unicode_content_round_trips(self):
        from scripts.asset_store import upsert_block

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "scene-index.md"
            upsert_block(path, "scene_1234abcd", "触发场景：发布前回归 ✅")
            self.assertIn("发布前回归 ✅", path.read_text(encoding="utf-8"))

    def test_filled_template_with_matching_markers_is_accepted_once(self):
        from scripts.asset_store import upsert_block

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "method-cards.md"
            filled = (
                "<!-- blc:start method_1234abcd -->\n"
                "method_id: method_1234abcd\n"
                "# 方法\n"
                "<!-- blc:end method_1234abcd -->\n"
            )
            upsert_block(path, "method_1234abcd", filled)
            text = path.read_text(encoding="utf-8")
            self.assertEqual(text.count("blc:start method_1234abcd"), 1)
            self.assertEqual(text.count("blc:end method_1234abcd"), 1)

    def test_invalid_id_is_rejected(self):
        from scripts.asset_store import upsert_block

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "notes.md"
            for entity_id in ("src-ch03-p014", "../escape", "note_NOTHEX", "method_123"):
                with self.subTest(entity_id=entity_id), self.assertRaises(ValueError):
                    upsert_block(path, entity_id, "内容")

    def test_append_event_retry_is_idempotent(self):
        from scripts.asset_store import append_event_once

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invocations.md"
            self.assertTrue(append_event_once(path, "invocation_1234abcd", "第一次调用"))
            self.assertFalse(append_event_once(path, "invocation_1234abcd", "重试内容"))
            text = path.read_text(encoding="utf-8")
            self.assertEqual(text.count("invocation_1234abcd"), 2)
            self.assertIn("第一次调用", text)
            self.assertNotIn("重试内容", text)


if __name__ == "__main__":
    unittest.main()
