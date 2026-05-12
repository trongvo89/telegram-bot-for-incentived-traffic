from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import aiosqlite

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent.parent / "migrations"


class State:
    """Lightweight SQLite DAO. Single connection per process."""

    def __init__(self, db_path: Path, tz: str) -> None:
        self._db_path = db_path
        self._tz = ZoneInfo(tz)
        self._conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self._db_path)
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA foreign_keys=ON")
        await self._run_migrations()

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    async def _run_migrations(self) -> None:
        assert self._conn is not None
        for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            await self._conn.executescript(path.read_text(encoding="utf-8"))
        await self._conn.commit()

    # ---- user → campaign --------------------------------------------------

    async def set_campaign(self, user_id: int, campaign: str) -> None:
        assert self._conn is not None
        await self._conn.execute(
            "INSERT INTO users_campaign(user_id, campaign, updated_at) "
            "VALUES(?, ?, CURRENT_TIMESTAMP) "
            "ON CONFLICT(user_id) DO UPDATE SET campaign=excluded.campaign, "
            "updated_at=CURRENT_TIMESTAMP",
            (user_id, campaign),
        )
        await self._conn.commit()

    async def get_campaign(self, user_id: int) -> str | None:
        assert self._conn is not None
        async with self._conn.execute(
            "SELECT campaign FROM users_campaign WHERE user_id = ?", (user_id,)
        ) as cur:
            row = await cur.fetchone()
        return row[0] if row else None

    # ---- uploads ---------------------------------------------------------

    async def exists_upload(self, file_unique_id: str, campaign: str) -> dict | None:
        assert self._conn is not None
        async with self._conn.execute(
            "SELECT id, status, created_at FROM uploads "
            "WHERE file_unique_id = ? AND campaign = ?",
            (file_unique_id, campaign),
        ) as cur:
            row = await cur.fetchone()
        if not row:
            return None
        return {"id": row[0], "status": row[1], "created_at": row[2]}

    async def insert_upload(
        self,
        *,
        user_id: int,
        username: str | None,
        campaign: str,
        file_unique_id: str,
        storage_chat_id: int | None,
        storage_msg_id: int | None,
        status: str,
    ) -> int:
        assert self._conn is not None
        cur = await self._conn.execute(
            "INSERT INTO uploads(user_id, username, campaign, file_unique_id, "
            "storage_chat_id, storage_msg_id, status) "
            "VALUES(?, ?, ?, ?, ?, ?, ?)",
            (user_id, username, campaign, file_unique_id, storage_chat_id, storage_msg_id, status),
        )
        await self._conn.commit()
        return cur.lastrowid or 0

    async def count_uploads_today(self, user_id: int) -> int:
        """Count uploads for user where created_at falls on 'today' in configured TZ."""
        assert self._conn is not None
        now_local = datetime.now(self._tz)
        start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
        end_local = start_local + timedelta(days=1)
        # SQLite stores CURRENT_TIMESTAMP as UTC naive string. Compare in UTC.
        start_utc = start_local.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%d %H:%M:%S")
        end_utc = end_local.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%d %H:%M:%S")
        async with self._conn.execute(
            "SELECT COUNT(*) FROM uploads WHERE user_id = ? "
            "AND created_at >= ? AND created_at < ?",
            (user_id, start_utc, end_utc),
        ) as cur:
            row = await cur.fetchone()
        return int(row[0]) if row else 0

    # ---- dead-letter -----------------------------------------------------

    async def push_dead_letter(self, payload: str, reason: str) -> int:
        assert self._conn is not None
        cur = await self._conn.execute(
            "INSERT INTO dead_letter(payload, reason) VALUES(?, ?)",
            (payload, reason),
        )
        await self._conn.commit()
        return cur.lastrowid or 0

    async def list_dead_letter(self, limit: int = 10, *, only_unresolved: bool = True) -> list[dict]:
        assert self._conn is not None
        sql = (
            "SELECT id, reason, created_at, resolved FROM dead_letter "
            + ("WHERE resolved = 0 " if only_unresolved else "")
            + "ORDER BY id DESC LIMIT ?"
        )
        async with self._conn.execute(sql, (limit,)) as cur:
            rows = await cur.fetchall()
        return [
            {"id": r[0], "reason": r[1], "created_at": r[2], "resolved": r[3]}
            for r in rows
        ]

    async def resolve_dead_letter(self, dl_id: int) -> bool:
        assert self._conn is not None
        cur = await self._conn.execute(
            "UPDATE dead_letter SET resolved = 1 WHERE id = ?",
            (dl_id,),
        )
        await self._conn.commit()
        return (cur.rowcount or 0) > 0
