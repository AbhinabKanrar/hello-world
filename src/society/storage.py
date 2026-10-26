"""Append-only JSONL I/O. Streams — memory is O(1) in population size."""

from __future__ import annotations

from collections.abc import AsyncIterable, Iterable, Iterator
from pathlib import Path

from pydantic import BaseModel


def write_jsonl(path: Path, rows: Iterable[BaseModel]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8", buffering=1 << 16) as fh:
        for row in rows:
            fh.write(row.model_dump_json())
            fh.write("\n")
            count += 1
    return count


async def write_jsonl_async(path: Path, rows: AsyncIterable[BaseModel]) -> int:
    """Stream rows produced by an async source; memory stays O(1) in row count."""
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8", buffering=1 << 16) as fh:
        async for row in rows:
            fh.write(row.model_dump_json())
            fh.write("\n")
            count += 1
    return count


def append_jsonl(path: Path, rows: Iterable[BaseModel]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("a", encoding="utf-8", buffering=1 << 16) as fh:
        for row in rows:
            fh.write(row.model_dump_json())
            fh.write("\n")
            count += 1
    return count


def read_jsonl[T: BaseModel](path: Path, model: type[T]) -> Iterator[T]:
    with path.open("r", encoding="utf-8") as fh:
        # for line in fh:
        #     if line := line.strip():
        for raw in fh:
            if line := raw.strip():
                yield model.model_validate_json(line)
