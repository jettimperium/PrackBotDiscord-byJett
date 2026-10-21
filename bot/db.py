"""SQLite-хранилище вызовов и откликов (без внешних зависимостей)."""

from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypeVar

T = TypeVar("T")

SCHEMA = """
CREATE TABLE IF NOT EXISTS calls (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id       INTEGER,
    channel_id     INTEGER,
    message_id     INTEGER,
    thread_id      INTEGER,
    author_id      INTEGER NOT NULL,
    author_name    TEXT NOT NULL,
    author_display TEXT NOT NULL,
    author_avatar  TEXT,
    quote          TEXT NOT NULL,
    mmr            TEXT NOT NULL,
    time_text      TEXT NOT NULL,
    server         TEXT NOT NULL,
    mode           TEXT NOT NULL,
    comment        TEXT,
    status         TEXT NOT NULL DEFAULT 'open',
    created_at     TEXT NOT NULL,
    closed_at      TEXT
);

CREATE TABLE IF NOT EXISTS responses (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    call_id    INTEGER NOT NULL REFERENCES calls(id) ON DELETE CASCADE,
    user_id    INTEGER NOT NULL,
    user_name  TEXT NOT NULL,
    team_level TEXT,
    note       TEXT,
    created_at TEXT NOT NULL,
    UNIQUE (call_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_calls_status ON calls(status);
CREATE INDEX IF NOT EXISTS idx_responses_call ON responses(call_id);
"""


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path

    # ------------------------------------------------------------------ utils
    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=15)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @contextmanager
    def _session(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    async def _run(self, work: Callable[[], T]) -> T:
        return await asyncio.to_thread(work)

    # ----------------------------------------------------------------- schema
    async def init(self) -> None:
        def work() -> None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self._session() as connection:
                connection.executescript(SCHEMA)

        await self._run(work)

    # ------------------------------------------------------------------ calls
    async def create_call(self, data: dict[str, Any]) -> int:
        columns = (
            "guild_id",
            "author_id",
            "author_name",
            "author_display",
            "author_avatar",
            "quote",
            "mmr",
            "time_text",
            "server",
            "mode",
            "comment",
            "created_at",
        )
        values = tuple(data.get(column) for column in columns[:-1]) + (
            data.get("created_at") or _now(),
        )
        sql = f"INSERT INTO calls ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})"

        def work() -> int:
            with self._session() as connection:
                cursor = connection.execute(sql, values)
                return int(cursor.lastrowid)

        return await self._run(work)

    async def attach_message(
        self,
        call_id: int,
        channel_id: int,
        message_id: int,
        thread_id: int | None,
    ) -> None:
        def work() -> None:
            with self._session() as connection:
                connection.execute(
                    "UPDATE calls SET channel_id = ?, message_id = ?, thread_id = ? WHERE id = ?",
                    (channel_id, message_id, thread_id, call_id),
                )

        await self._run(work)

    async def get_call(self, call_id: int) -> dict[str, Any] | None:
        def work() -> dict[str, Any] | None:
            with self._session() as connection:
                row = connection.execute("SELECT * FROM calls WHERE id = ?", (call_id,)).fetchone()
                return dict(row) if row else None

        return await self._run(work)

    async def open_calls(self) -> list[dict[str, Any]]:
        def work() -> list[dict[str, Any]]:
            with self._session() as connection:
                rows = connection.execute(
                    "SELECT * FROM calls WHERE status = 'open' AND message_id IS NOT NULL"
                ).fetchall()
                return [dict(row) for row in rows]

        return await self._run(work)

    async def count_open_calls(self, author_id: int) -> int:
        def work() -> int:
            with self._session() as connection:
                row = connection.execute(
                    "SELECT COUNT(*) FROM calls WHERE author_id = ? AND status = 'open'",
                    (author_id,),
                ).fetchone()
                return int(row[0])

        return await self._run(work)

    async def set_status(self, call_id: int, status: str) -> None:
        closed_at = _now() if status != "open" else None

        def work() -> None:
            with self._session() as connection:
                connection.execute(
                    "UPDATE calls SET status = ?, closed_at = ? WHERE id = ?",
                    (status, closed_at, call_id),
                )

        await self._run(work)

    async def close_by_message(self, message_id: int) -> None:
        def work() -> None:
            with self._session() as connection:
                connection.execute(
                    "UPDATE calls SET status = 'closed', closed_at = ? "
                    "WHERE message_id = ? AND status = 'open'",
                    (_now(), message_id),
                )

        await self._run(work)

    # -------------------------------------------------------------- responses
    async def add_response(
        self,
        call_id: int,
        user_id: int,
        user_name: str,
        team_level: str | None,
        note: str | None,
    ) -> None:
        def work() -> None:
            with self._session() as connection:
                connection.execute(
                    "INSERT INTO responses (call_id, user_id, user_name, team_level, note, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (call_id, user_id, user_name, team_level, note, _now()),
                )

        await self._run(work)

    async def get_response(self, call_id: int, user_id: int) -> dict[str, Any] | None:
        def work() -> dict[str, Any] | None:
            with self._session() as connection:
                row = connection.execute(
                    "SELECT * FROM responses WHERE call_id = ? AND user_id = ?",
                    (call_id, user_id),
                ).fetchone()
                return dict(row) if row else None

        return await self._run(work)

    async def responses(self, call_id: int) -> list[dict[str, Any]]:
        def work() -> list[dict[str, Any]]:
            with self._session() as connection:
                rows = connection.execute(
                    "SELECT * FROM responses WHERE call_id = ? ORDER BY id",
                    (call_id,),
                ).fetchall()
                return [dict(row) for row in rows]

        return await self._run(work)
