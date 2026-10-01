import copy
import json
import unittest
from pathlib import Path

try:
    from jsonschema import Draft202012Validator, ValidationError
except ModuleNotFoundError:  # Offline development fallback; runtime writes still fail closed.
    from tests.schema_compat import Draft202012Validator, ValidationError


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "assets" / "progress.schema.json"
FIXTURE_PATH = ROOT / "tests" / "fixtures" / "sample-book" / "minimal-progress.json"
TEMPLATE_PATH = ROOT / "assets" / "progress.template.json"


class ProgressSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(cls.schema)
        cls.validator = Draft202012Validator(cls.schema)
        cls.fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

    def assert_invalid(self, mutation):
        state = copy.deepcopy(self.fixture)
        mutation(state)
        with self.assertRaises(ValidationError):
            self.validator.validate(state)

    def test_minimal_progress_matches_schema(self):
        self.validator.validate(self.fixture)

    def test_progress_template_is_schema_and_semantically_valid(self):
        from scripts.progress import validate_semantics

        template = json.loads(TEMPLATE_PATH.read_text(encoding="utf-8"))
        self.validator.validate(template)
        validate_semantics(template)

    def test_root_last_completed_action_is_rejected(self):
        self.assert_invalid(lambda state: state.__setitem__("last_completed_action", "quiz_done"))

    def test_next_action_is_rejected(self):
        self.assert_invalid(lambda state: state.__setitem__("next_action", "continue"))

    def test_cursor_last_completed_action_is_allowed(self):
        state = copy.deepcopy(self.fixture)
        state["learning_cursor"]["last_completed_action"] = "explain_completed"
        self.validator.validate(state)

    def test_review_stage_outside_zero_to_five_is_rejected(self):
        self.assert_invalid(
            lambda state: state["review_cards"]["review_6ea7b190"].__setitem__("review_stage", 6)
        )

    def test_invalid_mode_phase_status_and_id_are_rejected(self):
        mutations = [
            lambda state: state["learning_cursor"].__setitem__("mode", "speedrun"),
            lambda state: state["learning_cursor"].__setitem__("mode", "browse"),
            lambda state: state["reading_cursor"].__setitem__("mode", "intensive"),
            lambda state: state["reading_cursor"].__setitem__("phase", "guess"),
            lambda state: state["lessons"]["lesson_83d712fa"].__setitem__("status", "done"),
            lambda state: state.__setitem__("book_id", "book-ordered-01"),
            lambda state: state["learning_cursor"].__setitem__("updated_at", "not-a-time"),
        ]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                self.assert_invalid(mutation)

    def test_reading_scope_shape_and_audit_scope_are_required(self):
        self.assert_invalid(lambda state: state.pop("reading_scope"))
        self.assert_invalid(lambda state: state["reading_scope"].pop("included_chapter_ids"))
        self.assert_invalid(lambda state: state["audit"].pop("book_status"))
        self.assert_invalid(lambda state: state["audit"]["chapters"].clear())

    def test_browse_status_and_reading_lens_are_required_and_constrained(self):
        self.assertIn("browse_status", self.fixture["chapters"]["ch_a14e90b2"])
        self.assertIn("reading_lens", self.fixture)
        self.assert_invalid(
            lambda state: state["chapters"]["ch_a14e90b2"].pop("browse_status")
        )
        self.assert_invalid(lambda state: state.pop("reading_lens"))
        self.assert_invalid(
            lambda state: state["reading_lens"].__setitem__("primary", "speed-reading")
        )

    def test_redundant_chapter_coverage_field_is_rejected(self):
        self.assert_invalid(
            lambda state: state["chapters"]["ch_a14e90b2"].__setitem__("coverage", "audited")
        )


if __name__ == "__main__":
    unittest.main()
