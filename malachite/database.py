import asyncio
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
        if self.last_hit is not None:
            last_hit = now - self.last_hit
            if last_hit.total_seconds() < (6 * 60 * 60):
                last_hit = f"\x0307{pretty_delta(last_hit)}\x03"
            else:
                last_hit = pretty_delta(last_hit)
        else:
            last_hit = "\x0312never\x03"
        active = "\x0313ACTIVE\x03" if self.active else "\x0311WARN\x03"
        return (f"#{self.id}: \x02{self.pattern}\x02 (\x1D{self.reason}\x1D) added {pretty_delta(now - self.added)}"
                f" by \x02{self.added_by}\x02 with \x02{self.hits}\x02 hits (last hit: {last_hit}) [{active}]")

    @property
    def full_reason(self) -> str:
        return f"mxbl #{self.id} - {self.reason}"


@dataclass
class Table:
    pool: Pool


class MxblTable(Table):
    async def get(self, id: int) -> MxblEntry | None:
        """
        get one entry by id
        """
        query = """
            SELECT *
            FROM mxbl
            WHERE id = $1
        """
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(query, id)
        if row is not None:
            return MxblEntry(*row)

    async def find(self, search: str) -> MxblEntry | None:
        """
        postgres glob search all entries
        """
        query = """
            SELECT *
            FROM mxbl
            WHERE pattern = $1
            ORDER BY id
            LIMIT 1
        """
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(query, search)
        if row is not None:
            return MxblEntry(*row)

    async def list_all(self, limit: int = 0, search: str = "") -> list[MxblEntry]:
        """
        list all entries up to limit (optional, default all) with an optional postgres glob filter
        """
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
        """
        add an entry
        """
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
        """
        delete an entry
        """
        query = """
            DELETE FROM mxbl
            WHERE id = $1
            RETURNING id
        """
        async with self.pool.acquire() as conn:
            return await conn.fetchval(query, id)

    async def edit_pattern(self, id: int, pattern: str) -> int:
        """
        update the pattern of an entry
        """
        query = """
            UPDATE mxbl
            SET pattern = $2
            WHERE id = $1
            RETURNING id
        """
        async with self.pool.acquire() as conn:
            return await conn.fetchval(query, id, pattern)

    async def edit_reason(self, id: int, reason: str) -> int:
        """
        update the reason of an entry
        """
        query = """
            UPDATE mxbl
            SET reason = $2
            WHERE id = $1
            RETURNING id
        """
        async with self.pool.acquire() as conn:
            return await conn.fetchval(query, id, reason)

    async def toggle(self, id: int) -> bool:
        """
        toggle a pattern active/warn by id
        """
        query = """
            UPDATE mxbl
            SET active = NOT active
            WHERE id = $1
            RETURNING active
        """
        async with self.pool.acquire() as conn:
            return await conn.fetchval(query, id)

    async def hit(self, id: int) -> int:
        """
        increment the hit counter and update the last_hit timestamp for an entry
        """
        query = """
            UPDATE mxbl
            SET hits = hits + 1, last_hit = NOW()::TIMESTAMP
            WHERE id = $1
            RETURNING hits
        """
        async with self.pool.acquire() as conn:
            return await conn.fetchval(query, id)


class SettingsTable(Table):
    async def get(self, name: str) -> str | None:
        query = """
            SELECT value
            FROM settings
            WHERE name = $1
            LIMIT 1
        """
        async with self.pool.acquire() as conn:
            return await conn.fetchval(query, name)

    async def get_all(self) -> dict[str, str]:
        query = """
            SELECT name, value
            FROM settings
            ORDER BY id
            LIMIT ALL
        """
        async with self.pool.acquire() as conn:
            resp = await conn.fetch(query)
        return {row["name"]: row["value"] for row in resp}

    async def set_(self, name: str, value: str):
        query = """
            INSERT INTO settings
            (name, value)
            VALUES ($1, $2)
            ON CONFLICT(name)
            DO UPDATE SET
                value = EXCLUDED.value
        """
        async with self.pool.acquire() as conn:
            await conn.fetchval(query, name, value)


class Database:
    def __init__(self, pool: Pool) -> None:
        self._pool = pool
        self.mxbl = MxblTable(pool)
        self.settings = SettingsTable(pool)

    @classmethod
    async def connect(cls, user: str, password: str | None, host: str | None, database: str | None):
        pool = await asyncpg.create_pool(user=user, password=password, host=host, database=database)
        return cls(pool)  # type: ignore

    def get_setting(self, name: str):
        return asyncio.create_task(self.settings.get(name))

    def get_all_settings(self):
        return asyncio.create_task(self.settings.get_all())

    def set_setting(self, name: str, value: str):
        return asyncio.create_task(self.settings.set_(name, value))

    def __getattr__(self, attr):
        """
        proxy the methods on MxblTable and wrap them in asyncio tasks
        to make awaiting database queries non-blocking
        """
        if hasattr(self.mxbl, attr):
            def wrapper(*args, **kwargs):
                return asyncio.create_task(getattr(self.mxbl, attr)(*args, **kwargs))
            return wrapper
        raise AttributeError(attr)
