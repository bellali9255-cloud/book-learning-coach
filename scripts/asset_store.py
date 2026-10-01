"""Deterministic, stable-ID Markdown block persistence."""

from __future__ import annotations

import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path


ENTITY_ID_RE = re.compile(
    r"^(?:ch|lesson|note|review|method|scene|mapping|invocation)_[0-9a-f]{8}$"
)
START_RE = re.compile(r"^<!-- blc:start ([a-z]+_[0-9a-f]{8}) -->$")
END_RE = re.compile(r"^<!-- blc:end ([a-z]+_[0-9a-f]{8}) -->$")


@dataclass(frozen=True)
class Block:
    entity_id: str
    start: int
    end: int


def _validate_id(entity_id: str) -> None:
    if ENTITY_ID_RE.fullmatch(entity_id) is None:
        raise ValueError(f"invalid stable entity ID: {entity_id!r}")


def _parse_blocks(text: str, *, allow_duplicates: bool = False) -> list[Block]:
    blocks: list[Block] = []
    open_block: tuple[str, int] | None = None
    seen: set[str] = set()
    offset = 0
    for line in text.splitlines(keepends=True):
        marker = line.rstrip("\r\n")
        start = START_RE.fullmatch(marker)
        end = END_RE.fullmatch(marker)
        if "<!-- blc:start" in marker and start is None:
            raise ValueError(f"malformed start marker: {marker!r}")
        if "<!-- blc:end" in marker and end is None:
            raise ValueError(f"malformed end marker: {marker!r}")
        if start:
            entity_id = start.group(1)
            _validate_id(entity_id)
            if open_block is not None:
                raise ValueError("nested blc blocks are not allowed")
            if not allow_duplicates and entity_id in seen:
                raise ValueError(f"duplicate blc block: {entity_id}")
            open_block = (entity_id, offset)
        elif end:
            entity_id = end.group(1)
            _validate_id(entity_id)
            if open_block is None:
                raise ValueError(f"end marker without start: {entity_id}")
            if open_block[0] != entity_id:
                raise ValueError(f"mismatched blc markers: {open_block[0]} != {entity_id}")
            blocks.append(Block(entity_id, open_block[1], offset + len(line)))
            seen.add(entity_id)
            open_block = None
        offset += len(line)
    if open_block is not None:
        raise ValueError(f"unclosed blc block: {open_block[0]}")
    return blocks


def _render_block(entity_id: str, content: str) -> str:
    body = content.strip("\r\n")
    if "<!-- blc:" in body:
        prewrapped = body + "\n"
        blocks = _parse_blocks(prewrapped, allow_duplicates=False)
        if (
            len(blocks) != 1
            or blocks[0].entity_id != entity_id
            or blocks[0].start != 0
            or blocks[0].end != len(prewrapped)
        ):
            raise ValueError("pre-wrapped content must contain exactly the matching entity block")
        return prewrapped
    return (
        f"<!-- blc:start {entity_id} -->\n"
        f"{body}\n"
        f"<!-- blc:end {entity_id} -->\n"
    )


def _atomic_write(path: Path, text: str) -> None:
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
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
            temporary_path = Path(handle.name)
        reread = temporary_path.read_text(encoding="utf-8")
        _parse_blocks(reread, allow_duplicates=False)
        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def upsert_block(path: Path, entity_id: str, content: str) -> None:
    """Create or replace exactly one block with ``entity_id``."""
    _validate_id(entity_id)
    path = Path(path)
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    blocks = _parse_blocks(text, allow_duplicates=False)
    target = next((block for block in blocks if block.entity_id == entity_id), None)
    rendered = _render_block(entity_id, content)
    if target is None:
        prefix = text.rstrip()
        updated = f"{prefix}\n\n{rendered}" if prefix else rendered
    else:
        updated = text[: target.start] + rendered + text[target.end :]
    _atomic_write(path, updated)


def replace_block(path: Path, entity_id: str, content: str) -> None:
    """Replace an existing block; never create it implicitly."""
    _validate_id(entity_id)
    path = Path(path)
    if not path.exists():
        raise KeyError(entity_id)
    text = path.read_text(encoding="utf-8")
    blocks = _parse_blocks(text, allow_duplicates=False)
    target = next((block for block in blocks if block.entity_id == entity_id), None)
    if target is None:
        raise KeyError(entity_id)
    updated = text[: target.start] + _render_block(entity_id, content) + text[target.end :]
    _atomic_write(path, updated)


def dedupe_blocks(path: Path) -> list[str]:
    """Remove earlier duplicate blocks, keeping the last complete occurrence."""
    path = Path(path)
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    blocks = _parse_blocks(text, allow_duplicates=True)
    last_index: dict[str, int] = {}
    counts: dict[str, int] = {}
    for index, block in enumerate(blocks):
        last_index[block.entity_id] = index
        counts[block.entity_id] = counts.get(block.entity_id, 0) + 1
    duplicates = sorted(entity_id for entity_id, count in counts.items() if count > 1)
    if not duplicates:
        return []
    pieces: list[str] = []
    cursor = 0
    for index, block in enumerate(blocks):
        pieces.append(text[cursor : block.start])
        if last_index[block.entity_id] == index:
            pieces.append(text[block.start : block.end])
        cursor = block.end
    pieces.append(text[cursor:])
    updated = "".join(pieces)
    _parse_blocks(updated, allow_duplicates=False)
    _atomic_write(path, updated)
    return duplicates


def append_event_once(path: Path, event_id: str, content: str) -> bool:
    """Append a unique event block and return whether a write occurred."""
    _validate_id(event_id)
    path = Path(path)
    if path.exists():
        blocks = _parse_blocks(path.read_text(encoding="utf-8"), allow_duplicates=False)
        if any(block.entity_id == event_id for block in blocks):
            return False
    upsert_block(path, event_id, content)
    return True
