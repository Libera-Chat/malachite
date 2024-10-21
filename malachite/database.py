from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import asyncpg
from asyncpg import Pool


def pretty_delta(d: timedelta) -> str:
    weeks, days = divmod(d.days, 7)
    hours, rem = divmod(d.seconds, (60 * 60))
    minutes, seconds = divmod(rem, 60)

    if weeks > 0:
        return f"{weeks}w{days}d ago"
    elif days > 0:
        return f"{days}d{hours}h ago"
    elif hours > 0:
        return f"{hours}h{minutes}m ago"
    elif minutes > 0:
        return f"{minutes}m{seconds}s ago"
    return f"{seconds}s ago"


@dataclass
class MxblEntry:
    id: int
    pattern: str
    reason: str
    active: bool
    added: datetime
    added_by: str
    hits: int
    last_hit: datetime | None

    def __str__(self) -> str:
        now = datetime.now(UTC)
        last_hit = pretty_delta(now - self.last_hit) if self.last_hit is not None else "never"
        active = "ENABLED" if self.active else "DISABLED"
        return (f"#{self.id}: {self.pattern} added {pretty_delta(now - self.added)} by {self.added_by}"
                f" with {self.hits} hits (last hit: {last_hit}) [{active}]")

    @property
    def full_reason(self) -> str:
        return f"mxbl #{self.id} - {self.reason}"


@dataclass
class Table:
    pool: Pool


class MxblTable(Table):
    async def get(self, id: int) -> MxblEntry:
        query = """
            SELECT *
            FROM mxbl
            WHERE id = $1
        """
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(query, id)
        return MxblEntry(*row)

    async def match_enabled(self, search: str) -> MxblEntry | None:
        query = """
            SELECT *
            FROM mxbl
            WHERE pattern = $1 AND active = true
            ORDER BY id
            LIMIT 1
        """
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(query, search)
        if row is not None:
            return MxblEntry(*row)

    async def list_all(self, limit: int = 0, search: str = "") -> list[MxblEntry]:
        query = """
            SELECT *
            FROM mxbl
            WHERE pattern LIKE $1
            ORDER BY id
            LIMIT $2
        """
        search = search.replace("*", "%").replace("?", "_")
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query, search or "%", limit or None)
        return [MxblEntry(*row) for row in rows]

    async def add(self, pattern: str, reason: str, active: bool, added_by: str) -> int:
        query = """
            INSERT INTO mxbl
            (pattern, reason, active, added, added_by)
            VALUES ($1, $2, $3, NOW()::TIMESTAMP, $4)
            RETURNING id
        """
        args = [pattern, reason, active, added_by]
        async with self.pool.acquire() as conn:
            return await conn.fetchval(query, *args)

    async def delete(self, id: int) -> int:
        query = """
            DELETE FROM mxbl
            WHERE id = $1
            RETURNING id
        """
        async with self.pool.acquire() as conn:
            return await conn.fetchval(query, id)

    async def toggle(self, id: int) -> bool:
        query = """
            UPDATE mxbl
            SET active = NOT active
            WHERE id = $1
            RETURNING active
        """
        async with self.pool.acquire() as conn:
            return await conn.fetchval(query, id)

    async def hit(self, id: int) -> int:
        query = """
            UPDATE mxbl
            SET hits = hits + 1, last_hit = NOW()::TIMESTAMP
            WHERE id = $1
            RETURNING hits
        """
        async with self.pool.acquire() as conn:
            return await conn.fetchval(query, id)

class Database:
    def __init__(self, pool: Pool) -> None:
        self._pool = pool
        self.mxbl = MxblTable(pool)

    @classmethod
    async def connect(cls, user: str, password: str | None, host: str | None, database: str | None):
        pool = await asyncpg.create_pool(user=user, password=password, host=host, database=database)
        return cls(pool)  # type: ignore
