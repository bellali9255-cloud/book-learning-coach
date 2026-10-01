import copy
import json
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from tests import schema_compat


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "assets" / "progress.schema.json"
FIXTURE_PATH = ROOT / "tests" / "fixtures" / "sample-book" / "minimal-progress.json"
COMPAT = types.SimpleNamespace(
    Draft202012Validator=schema_compat.Draft202012Validator,
    ValidationError=schema_compat.ValidationError,
)


class ProgressPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.state = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        self.validator_patch = patch("scripts.progress._import_jsonschema", return_value=COMPAT)
        self.validator_patch.start()
        self.addCleanup(self.validator_patch.stop)

    def test_valid_state_round_trips(self):
        from scripts.progress import atomic_write_progress, load_progress

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "progress.json"
            atomic_write_progress(path, self.state, SCHEMA_PATH)
            self.assertEqual(load_progress(path, SCHEMA_PATH), self.state)

    def test_invalid_existing_state_blocks_write(self):
        from scripts.progress import atomic_write_progress

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "progress.json"
            path.write_text('{"broken": true}', encoding="utf-8")
            before = path.read_bytes()
            with self.assertRaises(Exception):
                atomic_write_progress(path, self.state, SCHEMA_PATH)
            self.assertEqual(path.read_bytes(), before)

    def test_invalid_new_state_does_not_replace_old_file(self):
        from scripts.progress import atomic_write_progress

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "progress.json"
            atomic_write_progress(path, self.state, SCHEMA_PATH)
            before = path.read_bytes()
            invalid = copy.deepcopy(self.state)
            invalid["next_action"] = "continue"
            with self.assertRaises(Exception):
                atomic_write_progress(path, invalid, SCHEMA_PATH)
            self.assertEqual(path.read_bytes(), before)

    def test_missing_jsonschema_blocks_write_but_allows_raw_read(self):
        from scripts.progress import atomic_write_progress, load_raw_progress

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "progress.json"
            path.write_text(json.dumps(self.state), encoding="utf-8")
            self.assertEqual(load_raw_progress(path)["book_id"], self.state["book_id"])
            with patch("scripts.progress._import_jsonschema", side_effect=ModuleNotFoundError("jsonschema")):
                with self.assertRaisesRegex(RuntimeError, "jsonschema"):
                    atomic_write_progress(path, self.state, SCHEMA_PATH)

    def test_atomic_replace_failure_preserves_old_file(self):
        from scripts.progress import atomic_write_progress

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "progress.json"
            atomic_write_progress(path, self.state, SCHEMA_PATH)
            before = path.read_bytes()
            changed = copy.deepcopy(self.state)
            changed["book"]["title"] = "改变后的标题"
            with patch("scripts.progress.os.replace", side_effect=OSError("simulated replace failure")):
                with self.assertRaisesRegex(OSError, "replace failure"):
                    atomic_write_progress(path, changed, SCHEMA_PATH)
            self.assertEqual(path.read_bytes(), before)

    def test_scope_sets_must_be_disjoint_complete_and_have_reasons(self):
        from scripts.progress import validate_semantics

        overlap = copy.deepcopy(self.state)
        overlap["reading_scope"]["excluded_chapter_ids"] = ["ch_a14e90b2"]
        overlap["reading_scope"]["exclusion_reasons"] = {"ch_a14e90b2": "附录"}
        with self.assertRaisesRegex(ValueError, "disjoint"):
            validate_semantics(overlap)

        missing = copy.deepcopy(self.state)
        missing["reading_scope"]["included_chapter_ids"] = []
        with self.assertRaisesRegex(ValueError, "classify"):
            validate_semantics(missing)

        no_reason = copy.deepcopy(self.state)
        no_reason["reading_scope"]["included_chapter_ids"] = []
        no_reason["reading_scope"]["excluded_chapter_ids"] = ["ch_a14e90b2"]
        with self.assertRaisesRegex(ValueError, "reason"):
            validate_semantics(no_reason)

    def test_cursor_references_must_resolve_and_learning_lesson_must_match_chapter(self):
        from scripts.progress import validate_semantics

        unknown_chapter = copy.deepcopy(self.state)
        unknown_chapter["reading_cursor"]["chapter_id"] = "ch_deadbeef"
        with self.assertRaisesRegex(ValueError, "reading_cursor"):
            validate_semantics(unknown_chapter)

        unknown_lesson = copy.deepcopy(self.state)
        unknown_lesson["learning_cursor"]["lesson_id"] = "lesson_deadbeef"
        with self.assertRaisesRegex(ValueError, "learning_cursor"):
            validate_semantics(unknown_lesson)

        mismatch = copy.deepcopy(self.state)
        mismatch["chapters"]["ch_22222222"] = {
            "chapter_id": "ch_22222222",
            "title": "第二章",
            "display_order": 2,
            "browse_status": "unseen",
            "deep_read_status": "not_started",
            "source_block_ids": [],
        }
        mismatch["reading_scope"]["included_chapter_ids"].append("ch_22222222")
        mismatch["audit"]["chapters"]["ch_22222222"] = {
            "status": "not_started",
            "audited_at": None,
            "issues": [],
        }
        mismatch["learning_cursor"]["chapter_id"] = "ch_22222222"
        with self.assertRaisesRegex(ValueError, "same chapter"):
            validate_semantics(mismatch)

    def test_semantic_validation_rejects_impossible_or_naive_timestamps(self):
        from scripts.progress import validate_semantics

        impossible = copy.deepcopy(self.state)
        impossible["learning_cursor"]["updated_at"] = "2026-99-01T15:00:00+08:00"
        with self.assertRaisesRegex(ValueError, "timestamp"):
            validate_semantics(impossible)
        naive = copy.deepcopy(self.state)
        naive["reading_cursor"]["updated_at"] = "2026-10-01T15:00:00"
        with self.assertRaisesRegex(ValueError, "timestamp"):
            validate_semantics(naive)

    def test_unsupported_schema_version_fails_closed(self):
        from scripts.progress import validate_progress

        future = copy.deepcopy(self.state)
        future["schema_version"] = "2.0.0"
        with self.assertRaises(Exception):
            validate_progress(future, SCHEMA_PATH)

    def test_mastered_requires_a_recomputed_passing_attempt(self):
        from scripts.progress import validate_semantics

        no_attempt = copy.deepcopy(self.state)
        no_attempt["lessons"]["lesson_83d712fa"]["quiz_attempts"] = []
        with self.assertRaisesRegex(ValueError, "passing quiz attempt"):
            validate_semantics(no_attempt)

        inconsistent = copy.deepcopy(self.state)
        inconsistent["lessons"]["lesson_83d712fa"]["quiz_attempts"] = [
            {
                "attempt_id": "attempt_2c91f812",
                "score": 100,
                "must_know_passed": True,
                "passed": True,
                "at": "2026-10-01T14:30:00+08:00",
                "items": [
                    {
                        "question_id": "q_62cb190e",
                        "rubric_points": [
                            {
                                "point_id": "rp_7180ea5a",
                                "points": 100,
                                "earned_points": 60,
                                "must_know": True,
                                "passed": False,
                            }
                        ],
                    }
                ],
            }
        ]
        with self.assertRaisesRegex(ValueError, "summary"):
            validate_semantics(inconsistent)


class ProgressTransitionTests(unittest.TestCase):
    def setUp(self):
        self.state = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

    def test_explicit_resume_intents_select_the_matching_cursor(self):
        from scripts.progress import select_resume_cursor

        self.assertEqual(select_resume_cursor(self.state, "继续学"), "learning_cursor")
        self.assertEqual(select_resume_cursor(self.state, "继续拆"), "reading_cursor")
        self.state["reading_cursor"]["mode"] = "browse"
        self.assertEqual(select_resume_cursor(self.state, "继续浏览"), "reading_cursor")
        self.assertIsNone(select_resume_cursor(self.state, "继续拆"))

    def test_generic_resume_uses_only_cursor_timestamps(self):
        from scripts.progress import select_resume_cursor

        self.state["updated_at"] = "2099-01-01T00:00:00+00:00"
        self.state["last_invocation"] = {
            "method_ids": ["method_1234abcd"],
            "at": "2099-01-01T00:00:00+00:00",
        }
        self.assertEqual(select_resume_cursor(self.state, "继续"), "learning_cursor")
        self.state["reading_cursor"]["updated_at"] = "2026-10-01T16:00:00+08:00"
        self.assertEqual(select_resume_cursor(self.state, None), "reading_cursor")

    def test_resume_timestamp_tie_requires_user_choice(self):
        from scripts.progress import select_resume_cursor

        self.state["reading_cursor"]["updated_at"] = self.state["learning_cursor"]["updated_at"]
        self.assertIsNone(select_resume_cursor(self.state, "继续"))

    def test_resume_ignores_complete_cursors_and_handles_bad_timestamps(self):
        from scripts.progress import select_resume_cursor

        state = copy.deepcopy(self.state)
        state["learning_cursor"]["phase"] = "complete"
        state["learning_cursor"]["updated_at"] = "2099-01-01T00:00:00+00:00"
        self.assertEqual(select_resume_cursor(state, "继续"), "reading_cursor")
        state["reading_cursor"]["phase"] = "complete"
        self.assertIsNone(select_resume_cursor(state, "继续"))

        bad = copy.deepcopy(self.state)
        bad["reading_cursor"]["updated_at"] = "not-a-time"
        self.assertIsNone(select_resume_cursor(bad, "继续"))

    def test_score_attempt_enforces_eighty_and_must_know(self):
        from scripts.progress import score_attempt

        points = [
            {"points": 60, "earned_points": 60, "must_know": True, "passed": True},
            {"points": 40, "earned_points": 20, "must_know": False, "passed": False},
        ]
        self.assertEqual(score_attempt(points), (80, True, True))
        points[0]["passed"] = False
        self.assertEqual(score_attempt(points), (80, False, False))

    def test_phase_transition_updates_only_the_selected_cursor(self):
        from scripts.progress import advance_phase

        reading_before = copy.deepcopy(self.state["reading_cursor"])
        updated = advance_phase(
            self.state,
            scope="learning",
            event="feynman_completed",
            at="2026-10-01T16:00:00+08:00",
        )
        self.assertEqual(updated["learning_cursor"]["phase"], "quiz")
        self.assertEqual(updated["learning_cursor"]["last_completed_action"], "feynman_completed")
        self.assertEqual(updated["reading_cursor"], reading_before)

    def test_invocation_transition_changes_only_invocation_metadata(self):
        from scripts.progress import record_invocation

        before = copy.deepcopy(self.state)
        updated = record_invocation(
            self.state,
            ["method_1234abcd"],
            "2026-10-01T16:00:00+08:00",
        )
        self.assertEqual(updated["last_invocation"]["method_ids"], ["method_1234abcd"])
        self.assertEqual(updated["last_invocation"]["at"], "2026-10-01T16:00:00+08:00")
        for key in (
            "learning_cursor",
            "reading_cursor",
            "reading_scope",
            "chapters",
            "lessons",
            "review_cards",
            "audit",
        ):
            self.assertEqual(updated[key], before[key], key)
        self.assertEqual(self.state, before)
        with self.assertRaisesRegex(ValueError, "method_id"):
            record_invocation(self.state, ["method-ordered-1"], "2026-10-01T16:00:00+08:00")

    def test_review_stage_progression_and_floor(self):
        from scripts.progress import apply_review_result

        passed = apply_review_result(
            copy.deepcopy(self.state),
            "lesson_83d712fa",
            "review_6ea7b190",
            True,
            "cycle_11111111",
            "2026-10-02T15:00:00+08:00",
        )
        card = passed["review_cards"]["review_6ea7b190"]
        self.assertEqual(card["review_stage"], 1)
        self.assertEqual(card["review_status"], "scheduled")
        self.assertEqual(card["next_due_at"], "2026-10-05T15:00:00+08:00")

        stage_four = copy.deepcopy(self.state)
        stage_four["review_cards"]["review_6ea7b190"]["review_stage"] = 4
        mature = apply_review_result(
            stage_four,
            "lesson_83d712fa",
            "review_6ea7b190",
            True,
            "cycle_22222222",
            "2026-10-02T15:00:00+08:00",
        )
        card = mature["review_cards"]["review_6ea7b190"]
        self.assertEqual((card["review_stage"], card["review_status"], card["next_due_at"]), (5, "mature", None))

        stage_zero = copy.deepcopy(self.state)
        failed = apply_review_result(
            stage_zero,
            "lesson_83d712fa",
            "review_6ea7b190",
            False,
            "cycle_33333333",
            "2026-10-02T15:00:00+08:00",
        )
        card = failed["review_cards"]["review_6ea7b190"]
        self.assertEqual(card["review_stage"], 0)
        self.assertEqual(card["review_status"], "needs_review")
        self.assertEqual(failed["lessons"]["lesson_83d712fa"]["status"], "needs_review")

    def test_review_failure_from_stage_three_returns_to_stage_two(self):
        from scripts.progress import apply_review_result

        state = copy.deepcopy(self.state)
        state["review_cards"]["review_6ea7b190"]["review_stage"] = 3
        failed = apply_review_result(
            state,
            "lesson_83d712fa",
            "review_6ea7b190",
            False,
            "cycle_44444444",
            "2026-10-02T15:00:00+08:00",
        )
        card = failed["review_cards"]["review_6ea7b190"]
        self.assertEqual(card["review_stage"], 2)
        self.assertEqual(card["next_due_at"], "2026-10-09T15:00:00+08:00")

    def test_review_result_retry_is_idempotent_and_conflicts_require_regrade(self):
        from scripts.progress import apply_review_result

        cycle = "cycle_77777777"
        first = apply_review_result(
            copy.deepcopy(self.state),
            "lesson_83d712fa",
            "review_6ea7b190",
            True,
            cycle,
            "2026-10-02T15:00:00+08:00",
        )
        retry = apply_review_result(
            first,
            "lesson_83d712fa",
            "review_6ea7b190",
            True,
            cycle,
            "2026-10-02T15:00:00+08:00",
        )
        self.assertEqual(retry, first)
        with self.assertRaisesRegex(ValueError, "regrade"):
            apply_review_result(
                first,
                "lesson_83d712fa",
                "review_6ea7b190",
                False,
                cycle,
                "2026-10-02T15:05:00+08:00",
            )

    def test_lesson_recovers_only_after_all_required_cards_pass_current_cycle(self):
        from scripts.progress import apply_review_result, can_restore_mastered

        state = self._state_with_three_cards()
        cycle = "cycle_55555555"
        state = apply_review_result(state, "lesson_83d712fa", "review_6ea7b190", False, cycle, "2026-10-02T15:00:00+08:00")
        state = apply_review_result(state, "lesson_83d712fa", "review_22222222", True, cycle, "2026-10-02T15:01:00+08:00")
        self.assertFalse(can_restore_mastered(state, "lesson_83d712fa", cycle))
        self.assertEqual(state["lessons"]["lesson_83d712fa"]["status"], "needs_review")

        state = apply_review_result(
            state,
            "lesson_83d712fa",
            "review_6ea7b190",
            True,
            cycle,
            "2026-10-02T15:02:00+08:00",
            regrade=True,
        )
        self.assertTrue(can_restore_mastered(state, "lesson_83d712fa", cycle))
        self.assertEqual(state["lessons"]["lesson_83d712fa"]["status"], "mastered")

    def test_source_change_or_unresolved_must_know_blocks_recovery(self):
        from scripts.progress import can_restore_mastered

        state = self._state_with_three_cards()
        cycle = "cycle_66666666"
        for card_id in ("review_6ea7b190", "review_22222222"):
            state["review_cards"][card_id]["cycle_results"][cycle] = {
                "passed": True,
                "at": "2026-10-02T15:00:00+08:00",
            }
        stale = copy.deepcopy(state)
        stale["source"]["canonical_sha256"] = "c" * 64
        self.assertFalse(can_restore_mastered(stale, "lesson_83d712fa", cycle))
        unresolved = copy.deepcopy(state)
        unresolved["lessons"]["lesson_83d712fa"]["unresolved_must_know"] = ["核心定义"]
        self.assertFalse(can_restore_mastered(unresolved, "lesson_83d712fa", cycle))

    def _state_with_three_cards(self):
        state = copy.deepcopy(self.state)
        base = copy.deepcopy(state["review_cards"]["review_6ea7b190"])
        required = copy.deepcopy(base)
        required["review_card_id"] = "review_22222222"
        optional = copy.deepcopy(base)
        optional["review_card_id"] = "review_33333333"
        optional["required"] = False
        state["review_cards"]["review_22222222"] = required
        state["review_cards"]["review_33333333"] = optional
        state["lessons"]["lesson_83d712fa"]["review_card_ids"] = [
            "review_6ea7b190",
            "review_22222222",
            "review_33333333",
        ]
        return state


if __name__ == "__main__":
    unittest.main()
