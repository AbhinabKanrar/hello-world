"""Local stage journals, independent of the provider response cache."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Iterator
from contextlib import closing
from pathlib import Path
from types import TracebackType
from typing import Self

from pydantic import BaseModel


class RecoveryJournal:
    def __init__(
        self, directory: Path | None, *, identity: str, source: Path | None = None
    ) -> None:
        if source is not None:
            path = source / "progress.sqlite"
            if not path.is_file():
                raise ValueError("Retry source has no stage recovery journal")
            with closing(
                sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
            ) as original:
                saved = original.execute(
                    "SELECT value FROM metadata WHERE key = 'identity'"
                ).fetchone()
                if saved is None or saved[0] != identity:
                    raise ValueError("Retry inputs, settings, model or prompts differ")
        if directory is not None:
            directory.mkdir(parents=True, exist_ok=False)
        self._conn = sqlite3.connect(
            directory / "progress.sqlite" if directory is not None else ":memory:",
        )
        try:
            self._conn.execute("PRAGMA synchronous=FULL")
            if source is not None:
                with closing(
                    sqlite3.connect(
                        (source / "progress.sqlite").resolve().as_uri() + "?mode=ro", uri=True
                    )
                ) as original:
                    original.backup(self._conn)
            else:
                self._conn.executescript(
                    "CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);"
                    "CREATE TABLE items (scope TEXT, position INTEGER, payload TEXT NOT NULL,"
                    " PRIMARY KEY(scope, position)) WITHOUT ROWID;"
                )
                with self._conn:
                    self._conn.execute("INSERT INTO metadata VALUES ('identity', ?)", (identity,))
        except BaseException:
            self._conn.close()
            raise

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self._conn.close()

    def state[T: BaseModel](self, model: type[T]) -> T | None:
        row = self._conn.execute("SELECT value FROM metadata WHERE key = 'state'").fetchone()
        return model.model_validate_json(row[0]) if row is not None else None

    def values[T: BaseModel](self, scope: str, model: type[T]) -> Iterator[tuple[int, T]]:
        for position, payload in self._conn.execute(
            "SELECT position, payload FROM items WHERE scope = ? ORDER BY position", (scope,)
        ):
            yield position, model.model_validate_json(payload)

    def save(self, scope: str, position: int, value: BaseModel) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT INTO items VALUES (?, ?, ?)", (scope, position, value.model_dump_json())
            )

    def advance(
        self,
        state: BaseModel,
        *,
        scope: str = "",
        rows: Iterable[tuple[int, BaseModel]] = (),
    ) -> None:
        with self._conn:
            self._conn.executemany(
                "INSERT INTO items VALUES (?, ?, ?)",
                ((scope, position, row.model_dump_json()) for position, row in rows),
            )
            self._conn.execute(
                "INSERT OR REPLACE INTO metadata VALUES ('state', ?)",
                (state.model_dump_json(),),
            )
