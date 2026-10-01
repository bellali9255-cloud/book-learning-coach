"""Validated, atomic state management for book-learning-coach.

All writes require the external ``jsonschema`` package. Reading raw JSON remains
available for recovery diagnostics when that dependency is missing.
"""

from __future__ import annotations

import argparse
import copy
import importlib
import json
import os
import re
import tempfile
from collections.abc import Mapping
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


SUPPORTED_SCHEMA_VERSION = "1.0.0"
DEFAULT_SCHEMA_PATH = Path(__file__).resolve().parents[1] / "assets" / "progress.schema.json"


def _import_jsonschema():
    return importlib.import_module("jsonschema")


def load_raw_progress(path: Path) -> dict[str, Any]:
    """Read JSON without validation for diagnostics and recovery evidence."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("progress root must be an object")
    return data


def _validator(schema_path: Path):
    try:
        jsonschema = _import_jsonschema()
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "jsonschema is required for validated progress operations; "
            "install requirements.txt before writing state"
        ) from exc
    schema = json.loads(Path(schema_path).read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(schema)
    return jsonschema.Draft202012Validator(schema)


def validate_progress(state: Mapping[str, object], schema_path: Path = DEFAULT_SCHEMA_PATH) -> None:
    """Validate schema shape and cross-field semantics, raising on any issue."""
    if state.get("schema_version") != SUPPORTED_SCHEMA_VERSION:
        raise ValueError(
            f"unsupported schema_version {state.get('schema_version')!r}; "
            f"expected {SUPPORTED_SCHEMA_VERSION!r}"
        )
    _validator(Path(schema_path)).validate(state)
    validate_semantics(state)


def validate_semantics(state: Mapping[str, object]) -> None:
    """Enforce invariants that JSON Schema cannot express across fields."""
    chapters = state.get("chapters")
    lessons = state.get("lessons")
    review_cards = state.get("review_cards")
    scope = state.get("reading_scope")
    audit = state.get("audit")
    source = state.get("source")
    if not all(isinstance(item, Mapping) for item in (chapters, lessons, review_cards, scope, audit, source)):
        raise ValueError("core progress sections must be objects")

    lens = state.get("reading_lens")
    if not isinstance(lens, Mapping):
        raise ValueError("reading_lens must be an object")
    if lens.get("primary") in lens.get("supporting", []):
        raise ValueError("reading_lens primary must not be repeated as supporting")

    timestamp_fields = []
    for cursor_name in ("learning_cursor", "reading_cursor"):
        cursor = state.get(cursor_name)
        if isinstance(cursor, Mapping):
            timestamp_fields.append((f"{cursor_name}.updated_at", cursor.get("updated_at")))
    timestamp_fields.extend(
        [
            ("updated_at", state.get("updated_at")),
            ("last_invocation.at", state.get("last_invocation", {}).get("at")),
        ]
    )
    for lesson_id, lesson in lessons.items():
        for index, attempt in enumerate(lesson.get("quiz_attempts", [])):
            timestamp_fields.append((f"lessons.{lesson_id}.quiz_attempts[{index}].at", attempt.get("at")))
    for card_id, card in review_cards.items():
        timestamp_fields.extend(
            [
                (f"review_cards.{card_id}.last_reviewed_at", card.get("last_reviewed_at")),
                (f"review_cards.{card_id}.next_due_at", card.get("next_due_at")),
            ]
        )
        for cycle_id, result in card.get("cycle_results", {}).items():
            timestamp_fields.append((f"review_cards.{card_id}.cycle_results.{cycle_id}.at", result.get("at")))
    for chapter_id, chapter_audit in audit.get("chapters", {}).items():
        timestamp_fields.append((f"audit.chapters.{chapter_id}.audited_at", chapter_audit.get("audited_at")))
    for label, value in timestamp_fields:
        if value in (None, ""):
            continue
        try:
            _parse_timestamp(str(value))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid timestamp at {label}: {exc}") from exc

    chapter_ids = set(chapters)
    included = set(scope.get("included_chapter_ids", []))
    excluded = set(scope.get("excluded_chapter_ids", []))
    reasons = scope.get("exclusion_reasons", {})
    if included & excluded:
        raise ValueError("reading_scope included and excluded sets must be disjoint")
    if included | excluded != chapter_ids:
        raise ValueError("reading_scope must classify every recognized chapter exactly once")
    if not isinstance(reasons, Mapping) or set(reasons) != excluded:
        raise ValueError("every excluded chapter must have exactly one exclusion reason")
    if any(not isinstance(reason, str) or not reason.strip() for reason in reasons.values()):
        raise ValueError("every excluded chapter must have a non-empty reason")

    audit_chapters = audit.get("chapters", {})
    if not isinstance(audit_chapters, Mapping) or set(audit_chapters) != chapter_ids:
        raise ValueError("audit.chapters must contain every recognized chapter exactly once")

    for chapter_id, chapter in chapters.items():
        if not isinstance(chapter, Mapping) or chapter.get("chapter_id") != chapter_id:
            raise ValueError(f"chapter key and chapter_id disagree: {chapter_id}")

    for lesson_id, lesson in lessons.items():
        if not isinstance(lesson, Mapping) or lesson.get("lesson_id") != lesson_id:
            raise ValueError(f"lesson key and lesson_id disagree: {lesson_id}")
        if lesson.get("chapter_id") not in chapters:
            raise ValueError(f"lesson references unknown chapter: {lesson_id}")
        for card_id in lesson.get("review_card_ids", []):
            if card_id not in review_cards:
                raise ValueError(f"lesson references unknown review card: {card_id}")

    learning_cursor = state.get("learning_cursor")
    if isinstance(learning_cursor, Mapping):
        chapter_id = learning_cursor.get("chapter_id")
        lesson_id = learning_cursor.get("lesson_id")
        if chapter_id not in chapters:
            raise ValueError("learning_cursor references an unknown chapter")
        if lesson_id not in lessons:
            raise ValueError("learning_cursor references an unknown lesson")
        if lessons[lesson_id].get("chapter_id") != chapter_id:
            raise ValueError("learning_cursor lesson and chapter must refer to the same chapter")
    reading_cursor = state.get("reading_cursor")
    if isinstance(reading_cursor, Mapping) and reading_cursor.get("chapter_id") not in chapters:
        raise ValueError("reading_cursor references an unknown chapter")

    source_hashes = {
        "original_sha256": source.get("original_sha256"),
        "canonical_sha256": source.get("canonical_sha256"),
    }
    for card_id, card in review_cards.items():
        if not isinstance(card, Mapping) or card.get("review_card_id") != card_id:
            raise ValueError(f"review card key and review_card_id disagree: {card_id}")
        lesson_id = card.get("lesson_id")
        if lesson_id not in lessons:
            raise ValueError(f"review card references unknown lesson: {card_id}")
        if card_id not in lessons[lesson_id].get("review_card_ids", []):
            raise ValueError(f"review card is not linked by its lesson: {card_id}")
        if card.get("review_stage") == 5:
            if card.get("review_status") != "mature" or card.get("next_due_at") is not None:
                raise ValueError("stage 5 review cards must be mature with next_due_at null")
        if card.get("review_status") == "mature" and card.get("review_stage") != 5:
            raise ValueError("only stage 5 review cards may be mature")

    for lesson_id, lesson in lessons.items():
        computed_attempts = []
        for attempt in lesson.get("quiz_attempts", []):
            rubric_points = [
                point
                for item in attempt.get("items", [])
                for point in item.get("rubric_points", [])
            ]
            computed = score_attempt(rubric_points)
            stored = (
                attempt.get("score"),
                attempt.get("must_know_passed"),
                attempt.get("passed"),
            )
            if stored != computed:
                raise ValueError(f"quiz attempt summary contradicts rubric points in {lesson_id}")
            computed_attempts.append(computed)
        hashes = lesson.get("source_hashes", {})
        if lesson.get("status") == "mastered" and hashes != source_hashes:
            raise ValueError(f"mastered lesson source hashes are stale: {lesson_id}")
        if lesson.get("status") == "mastered":
            if not computed_attempts or computed_attempts[-1][2] is not True:
                raise ValueError(f"mastered lesson requires a current passing quiz attempt: {lesson_id}")
            if lesson.get("mastery") != computed_attempts[-1][0]:
                raise ValueError(f"mastery must equal the latest valid quiz score: {lesson_id}")


def load_progress(path: Path, schema_path: Path = DEFAULT_SCHEMA_PATH) -> dict[str, Any]:
    state = load_raw_progress(Path(path))
    validate_progress(state, Path(schema_path))
    return state


def atomic_write_progress(
    path: Path,
    state: Mapping[str, object],
    schema_path: Path = DEFAULT_SCHEMA_PATH,
) -> None:
    """Validate old and new state, fsync a temp file, then atomically replace."""
    path = Path(path)
    schema_path = Path(schema_path)
    if path.exists():
        load_progress(path, schema_path)

    candidate = copy.deepcopy(dict(state))
    validate_progress(candidate, schema_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            json.dump(candidate, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
            temporary_path = Path(handle.name)

        serialized = load_raw_progress(temporary_path)
        validate_progress(serialized, schema_path)
        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def _parse_timestamp(value: str) -> datetime:
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp must include an RFC 3339 UTC offset")
    return parsed


def select_resume_cursor(state: Mapping[str, object], intent: str | None) -> str | None:
    """Select a cursor from explicit intent or cursor-local timestamps only.

    ``None`` means the user must choose because no compatible cursor exists or
    the two cursor timestamps tie. Root and invocation timestamps are ignored.
    """
    learning = state.get("learning_cursor")
    reading = state.get("reading_cursor")
    normalized = (intent or "").strip().lower()

    if normalized in {"继续学", "继续学习", "resume learning", "continue learning"}:
        return (
            "learning_cursor"
            if isinstance(learning, Mapping) and learning.get("phase") != "complete"
            else None
        )
    if normalized in {"继续拆", "继续拆书", "resume breakdown", "continue breakdown"}:
        if (
            isinstance(reading, Mapping)
            and reading.get("mode") == "breakdown"
            and reading.get("phase") != "complete"
        ):
            return "reading_cursor"
        return None
    if normalized in {"继续浏览", "resume browsing", "continue browsing"}:
        if (
            isinstance(reading, Mapping)
            and reading.get("mode") == "browse"
            and reading.get("phase") != "complete"
        ):
            return "reading_cursor"
        return None

    candidates = []
    try:
        if isinstance(learning, Mapping) and learning.get("phase") != "complete":
            candidates.append(("learning_cursor", _parse_timestamp(str(learning["updated_at"]))))
        if isinstance(reading, Mapping) and reading.get("phase") != "complete":
            candidates.append(("reading_cursor", _parse_timestamp(str(reading["updated_at"]))))
    except (KeyError, TypeError, ValueError):
        return None
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0][0]
    candidates.sort(key=lambda item: item[1], reverse=True)
    if candidates[0][1] == candidates[1][1]:
        return None
    return candidates[0][0]


def score_attempt(rubric_points) -> tuple[int, bool, bool]:
    """Return normalized score, must-know result, and overall pass result."""
    points = list(rubric_points)
    if not points:
        raise ValueError("at least one rubric point is required")
    total = 0.0
    earned = 0.0
    must_know_passed = True
    for point in points:
        possible = float(point["points"])
        received = float(point["earned_points"])
        if possible <= 0 or received < 0 or received > possible:
            raise ValueError("rubric points must satisfy 0 <= earned_points <= points")
        total += possible
        earned += received
        if point.get("must_know") and not point.get("passed"):
            must_know_passed = False
    score = round(earned / total * 100)
    passed = score >= 80 and must_know_passed
    return score, must_know_passed, passed


_LEARNING_TRANSITIONS = {
    ("assess", "assessment_completed"): "explain",
    ("explain", "explain_completed"): "feynman",
    ("feynman", "feynman_completed"): "quiz",
    ("quiz", "quiz_passed"): "distill",
    ("quiz", "quiz_failed"): "remediate",
    ("remediate", "remediation_completed"): "quiz",
    ("distill", "distill_completed"): "record",
    ("record", "record_completed"): "schedule_review",
    ("schedule_review", "review_scheduled"): "complete",
}

_READING_TRANSITIONS = {
    ("inspect", "inspection_completed"): "map_toc",
    ("map_toc", "toc_mapped"): "prioritize",
    ("prioritize", "priorities_set"): "chapter_read",
    ("chapter_read", "chapter_read_completed"): "chapter_notes",
    ("chapter_notes", "chapter_notes_completed"): "audit",
    ("audit", "audit_completed"): "complete",
}


def advance_phase(state: dict[str, object], scope: str, event: str, at: str) -> dict[str, object]:
    """Apply one legal phase transition and update only that cursor."""
    if scope not in {"learning", "reading"}:
        raise ValueError("scope must be 'learning' or 'reading'")
    updated = copy.deepcopy(state)
    cursor_name = f"{scope}_cursor"
    cursor = updated.get(cursor_name)
    if not isinstance(cursor, dict):
        raise ValueError(f"{cursor_name} is not active")
    transitions = _LEARNING_TRANSITIONS if scope == "learning" else _READING_TRANSITIONS
    key = (cursor.get("phase"), event)
    if key not in transitions:
        raise ValueError(f"invalid {scope} transition: {key[0]!r} + {event!r}")
    _parse_timestamp(at)
    cursor["phase"] = transitions[key]
    cursor["last_completed_action"] = event
    cursor["updated_at"] = at
    updated["updated_at"] = at
    return updated


_REVIEW_INTERVAL_DAYS = {0: 1, 1: 3, 2: 7, 3: 14, 4: 30}
_METHOD_ID_RE = re.compile(r"^method_[0-9a-f]{8}$")


def _due_at(at: str, stage: int) -> str | None:
    if stage == 5:
        return None
    return (_parse_timestamp(at) + timedelta(days=_REVIEW_INTERVAL_DAYS[stage])).isoformat()


def record_invocation(
    state: Mapping[str, object], method_ids, at: str
) -> dict[str, object]:
    """Create an invocation-only state transition without touching learning state."""
    ids = list(method_ids)
    if len(ids) != len(set(ids)) or any(_METHOD_ID_RE.fullmatch(item) is None for item in ids):
        raise ValueError("method_ids must be unique stable method_id values")
    _parse_timestamp(at)
    updated = copy.deepcopy(dict(state))
    protected = {
        key: copy.deepcopy(updated.get(key))
        for key in (
            "learning_cursor",
            "reading_cursor",
            "reading_scope",
            "reading_lens",
            "chapters",
            "lessons",
            "review_cards",
            "audit",
        )
    }
    updated["last_invocation"] = {"method_ids": ids, "at": at}
    updated["updated_at"] = at
    if any(updated.get(key) != value for key, value in protected.items()):
        raise RuntimeError("invocation transition attempted to mutate protected learning state")
    return updated


def atomic_record_invocation(
    path: Path,
    method_ids,
    at: str,
    schema_path: Path = DEFAULT_SCHEMA_PATH,
) -> dict[str, object]:
    state = load_progress(path, schema_path)
    updated = record_invocation(state, method_ids, at)
    atomic_write_progress(path, updated, schema_path)
    return updated


def can_restore_mastered(state: Mapping[str, object], lesson_id: str, cycle_id: str) -> bool:
    lessons = state.get("lessons", {})
    cards = state.get("review_cards", {})
    source = state.get("source", {})
    if lesson_id not in lessons or not isinstance(source, Mapping):
        return False
    lesson = lessons[lesson_id]
    if lesson.get("mastery", 0) < 80 or lesson.get("unresolved_must_know"):
        return False
    current_hashes = {
        "original_sha256": source.get("original_sha256"),
        "canonical_sha256": source.get("canonical_sha256"),
    }
    if lesson.get("source_hashes") != current_hashes:
        return False
    required_cards = []
    for card_id in lesson.get("review_card_ids", []):
        card = cards.get(card_id)
        if not isinstance(card, Mapping):
            return False
        if card.get("required"):
            required_cards.append(card)
    if not required_cards:
        return False
    for card in required_cards:
        if card.get("source_hashes") != current_hashes:
            return False
        result = card.get("cycle_results", {}).get(cycle_id)
        if not isinstance(result, Mapping) or result.get("passed") is not True:
            return False
    return True


def apply_review_result(
    state: dict[str, object],
    lesson_id: str,
    card_id: str,
    passed: bool,
    cycle_id: str,
    at: str,
    *,
    regrade: bool = False,
) -> dict[str, object]:
    """Record one card result and restore mastery only after the full cycle passes."""
    updated = copy.deepcopy(state)
    lesson = updated.get("lessons", {}).get(lesson_id)
    card = updated.get("review_cards", {}).get(card_id)
    if not isinstance(lesson, dict) or not isinstance(card, dict):
        raise ValueError("unknown lesson or review card")
    if card.get("lesson_id") != lesson_id or card_id not in lesson.get("review_card_ids", []):
        raise ValueError("review card does not belong to lesson")
    if not isinstance(passed, bool):
        raise ValueError("passed must be boolean")
    _parse_timestamp(at)
    if not cycle_id.startswith("cycle_"):
        raise ValueError("invalid cycle_id")

    existing_result = card.get("cycle_results", {}).get(cycle_id)
    candidate_result = {"passed": passed, "at": at}
    if existing_result == candidate_result:
        return updated
    if existing_result is not None and not regrade:
        raise ValueError("conflicting review result requires explicit regrade=True")

    old_stage = int(card["review_stage"])
    new_stage = min(old_stage + 1, 5) if passed else max(old_stage - 1, 0)
    card["review_stage"] = new_stage
    card["last_reviewed_at"] = at
    card["next_due_at"] = _due_at(at, new_stage)
    card["review_status"] = "mature" if new_stage == 5 else ("scheduled" if passed else "needs_review")
    card.setdefault("cycle_results", {})[cycle_id] = candidate_result

    if not passed and card.get("required"):
        lesson["status"] = "needs_review"
    elif lesson.get("status") == "needs_review" and can_restore_mastered(updated, lesson_id, cycle_id):
        lesson["status"] = "mastered"
    updated["updated_at"] = at
    return updated


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA_PATH)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("validate", "show", "raw-show"):
        subparser = subparsers.add_parser(command)
        subparser.add_argument("path", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command == "raw-show":
        state = load_raw_progress(args.path)
        print("UNVALIDATED RAW PROGRESS — diagnostics only")
        print(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    state = load_progress(args.path, args.schema)
    if args.command == "show":
        print(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"valid: {args.path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
