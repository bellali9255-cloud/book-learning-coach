"""Read-only workspace, traceability, and scoped eligibility audits."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from typing import Any

try:
    from scripts.progress import DEFAULT_SCHEMA_PATH, load_progress
    from scripts.asset_store import _parse_blocks
except ModuleNotFoundError:  # Support direct ``python scripts/audit_workspace.py`` use.
    from progress import DEFAULT_SCHEMA_PATH, load_progress
    from asset_store import _parse_blocks


SOURCE_ANCHOR_RE = re.compile(r'<a\s+id="(src_[0-9a-f]{8})"\s*></a>')
SOURCE_REF_RE = re.compile(r"(?m)^\s*source_block_id:\s*(src_[0-9a-f]{8})\s*$")
EXPECTED_PREFIX_BY_NAME = {
    "reading-notes.md": "note_",
    "review-cards.md": "review_",
    "method-cards.md": "method_",
    "scene-index.md": "scene_",
    "work-mapping.md": "mapping_",
    "invocation-log.md": "invocation_",
    "00_目录导读.md": "ch_",
}


def _markdown_files(root: Path, *, include_cache: bool = False) -> list[Path]:
    files = []
    for path in root.rglob("*.md"):
        relative = path.relative_to(root)
        if not include_cache and ".cache" in relative.parts:
            continue
        files.append(path)
    return sorted(files)


def _cache_anchors(root: Path) -> set[str]:
    cache = root / ".cache"
    if not cache.exists():
        return set()
    anchors: set[str] = set()
    for path in cache.rglob("*.md"):
        anchors.update(SOURCE_ANCHOR_RE.findall(path.read_text(encoding="utf-8")))
    return anchors


def audit_workspace(root: Path) -> dict[str, Any]:
    """Return a read-only report; errors never mutate progress or assets."""
    root = Path(root).resolve()
    report: dict[str, Any] = {
        "root": str(root),
        "hard_errors": [],
        "warnings": [],
        "chapters": {},
        "book": {"eligible": False, "errors": []},
    }

    progress_candidates = [
        path
        for path in root.rglob("progress.json")
        if ".cache" not in path.relative_to(root).parts
    ]
    if len(progress_candidates) != 1:
        report["hard_errors"].append(
            f"workspace must contain exactly one progress.json; found {len(progress_candidates)}"
        )
    progress_path = root / "learning" / "progress.json"
    if len(progress_candidates) == 1 and progress_candidates[0].resolve() != progress_path.resolve():
        report["hard_errors"].append("canonical progress.json must be learning/progress.json")
    state: Mapping[str, Any] | None = None
    try:
        state = load_progress(progress_path, DEFAULT_SCHEMA_PATH)
    except Exception as exc:  # Report invalid state; never treat it as usable truth.
        report["hard_errors"].append(f"progress validation failed: {exc}")

    if state is not None:
        for label, path_key, hash_key in (
            ("original", "original_path", "original_sha256"),
            ("canonical", "canonical_path", "canonical_sha256"),
        ):
            configured_path = (root / state["source"][path_key]).resolve()
            try:
                configured_path.relative_to(root)
            except ValueError:
                report["hard_errors"].append(f"{label} source path escapes workspace")
                continue
            if not configured_path.is_file():
                report["hard_errors"].append(f"{label} source file is missing: {configured_path}")
                continue
            actual_hash = hashlib.sha256(configured_path.read_bytes()).hexdigest()
            if actual_hash != state["source"][hash_key]:
                report["hard_errors"].append(
                    f"{hash_key} mismatch: progress has {state['source'][hash_key]}, file has {actual_hash}"
                )

    canonical_candidates = [
        path for path in _markdown_files(root) if path.name == "source.md"
    ]
    if len(canonical_candidates) != 1:
        report["hard_errors"].append(
            f"workspace must contain exactly one canonical source.md; found {len(canonical_candidates)}"
        )
    canonical_path = canonical_candidates[0] if len(canonical_candidates) == 1 else None
    if state is not None:
        configured = (root / state["source"]["canonical_path"]).resolve()
        if canonical_path is None or configured != canonical_path.resolve():
            report["hard_errors"].append("configured canonical source does not match the unique source.md")

    anchors: list[str] = []
    if canonical_path is not None:
        anchors = SOURCE_ANCHOR_RE.findall(canonical_path.read_text(encoding="utf-8"))
        for source_id, count in Counter(anchors).items():
            if count > 1:
                report["hard_errors"].append(f"duplicate source block ID in canonical source: {source_id}")
    anchor_set = set(anchors)
    cached = _cache_anchors(root)

    note_candidates = [
        path for path in _markdown_files(root) if path.name == "reading-notes.md"
    ]
    note_blocks_by_chapter: dict[str, list[tuple[str, set[str]]]] = {}
    if len(note_candidates) != 1:
        report["hard_errors"].append(
            f"workspace must contain exactly one canonical reading-notes.md; found {len(note_candidates)}"
        )
    else:
        notes_path = note_candidates[0]
        expected_notes = (root / "notes" / "reading-notes.md").resolve()
        if notes_path.resolve() != expected_notes:
            report["hard_errors"].append("canonical reading-notes.md must be notes/reading-notes.md")
        notes_text = notes_path.read_text(encoding="utf-8")
        try:
            note_blocks = _parse_blocks(notes_text, allow_duplicates=False)
        except ValueError as exc:
            report["hard_errors"].append(f"reading-notes marker validation failed: {exc}")
            note_blocks = []
        for block in note_blocks:
            if not block.entity_id.startswith("note_"):
                report["hard_errors"].append(
                    f"reading-notes block must use note_ stable ID: {block.entity_id}"
                )
                continue
            body = notes_text[block.start : block.end]
            chapter_match = re.search(
                r"(?m)^\s*chapter_id:\s*(ch_[0-9a-f]{8})\s*$", body
            )
            if chapter_match is None:
                report["hard_errors"].append(
                    f"reading-notes block lacks chapter_id: {block.entity_id}"
                )
                continue
            note_blocks_by_chapter.setdefault(chapter_match.group(1), []).append(
                (block.entity_id, set(SOURCE_REF_RE.findall(body)))
            )

    stable_ids: list[str] = []
    for path in _markdown_files(root):
        if canonical_path is not None and path.resolve() == canonical_path.resolve():
            continue
        text = path.read_text(encoding="utf-8")
        relative = path.relative_to(root)
        try:
            parsed_blocks = _parse_blocks(text, allow_duplicates=True)
        except ValueError as exc:
            report["hard_errors"].append(f"{relative} marker validation failed: {exc}")
            parsed_blocks = []
        expected_prefix = EXPECTED_PREFIX_BY_NAME.get(path.name)
        if expected_prefix is None and relative.parts and relative.parts[0] == "lessons":
            expected_prefix = "lesson_"
        for block in parsed_blocks:
            stable_ids.append(block.entity_id)
            if expected_prefix is not None and not block.entity_id.startswith(expected_prefix):
                report["hard_errors"].append(
                    f"{relative} blocks must use {expected_prefix} stable IDs, got {block.entity_id}"
                )
        for source_id in SOURCE_REF_RE.findall(text):
            if source_id not in anchor_set:
                if source_id in cached:
                    report["hard_errors"].append(
                        f".cache is never a backlink target: {source_id} exists only in .cache"
                    )
                else:
                    report["hard_errors"].append(
                        f"unresolved source_block_id in canonical source: {source_id}"
                    )
    for entity_id, count in Counter(stable_ids).items():
        if count > 1:
            report["hard_errors"].append(f"duplicate stable ID across Markdown assets: {entity_id}")

    if state is None:
        return report

    included = set(state["reading_scope"]["included_chapter_ids"])
    for chapter_id, chapter in state["chapters"].items():
        audit_state = state["audit"]["chapters"][chapter_id]
        chapter_errors = []
        for source_id in chapter["source_block_ids"]:
            if source_id not in anchor_set:
                chapter_errors.append(f"{chapter_id} references missing source block {source_id}")
        chapter_notes = note_blocks_by_chapter.get(chapter_id, [])
        if not chapter_notes:
            chapter_errors.append(f"{chapter_id} has no stable-ID block in canonical reading-notes.md")
        else:
            cited = set().union(*(source_ids for _, source_ids in chapter_notes))
            expected = set(chapter["source_block_ids"])
            outside = cited - expected
            missing = expected - cited
            if outside:
                chapter_errors.append(
                    f"{chapter_id} notes cite source blocks from another chapter: {sorted(outside)}"
                )
            if missing:
                chapter_errors.append(
                    f"{chapter_id} notes do not cover source blocks: {sorted(missing)}"
                )
        eligible = (
            chapter_id in included
            and chapter["deep_read_status"] == "audited"
            and audit_state["status"] == "audited"
            and not audit_state["issues"]
            and not chapter_errors
            and not report["hard_errors"]
        )
        report["chapters"][chapter_id] = {
            "eligible": eligible,
            "included": chapter_id in included,
            "status": audit_state["status"],
            "errors": chapter_errors,
            "audit_ref": f"learning/progress.json#audit.chapters.{chapter_id}",
        }

    book_errors = []
    for chapter_id in sorted(included):
        chapter_report = report["chapters"].get(chapter_id)
        if not chapter_report or not chapter_report["eligible"]:
            book_errors.append(f"included chapter is not audited: {chapter_id}")
    if state["audit"]["book_status"] != "audited":
        book_errors.append(
            f"book audit status is {state['audit']['book_status']!r}, not 'audited'"
        )
    report["book"] = {
        "eligible": not report["hard_errors"] and not book_errors,
        "status": state["audit"]["book_status"],
        "errors": book_errors,
        "included_chapter_ids": sorted(included),
    }
    return report


def audit_chapter(root: Path, chapter_id: str) -> dict[str, Any]:
    report = audit_workspace(root)
    if chapter_id not in report["chapters"]:
        report["hard_errors"].append(f"unknown chapter: {chapter_id}")
    else:
        report["hard_errors"].extend(report["chapters"][chapter_id]["errors"])
    report["requested_scope"] = "chapter"
    report["requested_chapter_id"] = chapter_id
    return report


def audit_book(root: Path) -> dict[str, Any]:
    report = audit_workspace(root)
    report["hard_errors"].extend(report["book"]["errors"])
    report["requested_scope"] = "book"
    return report


def can_emit_asset(
    audit: Mapping[str, object], scope: str, chapter_id: str | None = None
) -> bool:
    """Authorize formal knowledge assets only at the audited scope."""
    if audit.get("hard_errors"):
        return False
    if scope == "chapter":
        if chapter_id is None:
            return False
        chapter = audit.get("chapters", {}).get(chapter_id)
        return isinstance(chapter, Mapping) and chapter.get("eligible") is True
    if scope in {"book", "cross_chapter"}:
        book = audit.get("book")
        return isinstance(book, Mapping) and book.get("eligible") is True
    raise ValueError("scope must be chapter, book, or cross_chapter")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", nargs="?", type=Path, default=Path.cwd())
    parser.add_argument(
        "--scope", choices=("workspace", "chapter", "book"), default="workspace"
    )
    parser.add_argument("--chapter-id")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.scope == "chapter":
        if not args.chapter_id:
            raise SystemExit("--chapter-id is required for --scope chapter")
        report = audit_chapter(args.root, args.chapter_id)
    elif args.scope == "book":
        report = audit_book(args.root)
    else:
        report = audit_workspace(args.root)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 1 if report["hard_errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
