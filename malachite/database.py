import asyncio
from dataclasses import dataclass

import asyncpg
from asyncpg import Pool, Record

from .util import MxblEntry, Pattern, make_pattern


@dataclass
class Table:
    pool: Pool


class MxblTable(Table):
    async def get(self, id: int) -> MxblEntry | None:
        """
        get one entry by id
        """
        query = """
            SELECT id, pattern, pattern_type, reason, active, added, added_by, hits, last_hit
            FROM mxbl
            WHERE id = $1
        """
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(query, id)
        if row is not None:
            return MxblEntry.from_record(row)

    async def list_all(self, limit: int = 0, offset: int = 0, order_by: str = "id") -> list[MxblEntry]:
        """
        list all entries up to limit (optional, default all) from an offset (optional, default index 0)
        """
        query = f"""
            SELECT id, pattern, pattern_type, reason, active, added, added_by, hits, last_hit
            FROM mxbl
            ORDER BY {order_by}
            LIMIT $1
            OFFSET $2
        """
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query, limit or None, offset)
        return [MxblEntry.from_record(row) for row in rows]

    async def add(self, pattern: Pattern, reason: str, active: bool, added_by: str) -> tuple[int, Pattern] | None:
        """
        add an entry
        """
        query = """
            INSERT INTO mxbl
            (pattern, pattern_type, reason, active, added, added_by)
            VALUES ($1, $2, $3, $4, NOW()::TIMESTAMP, $5)
            RETURNING id, pattern, pattern_type
        """
        args = [pattern.raw, pattern.ty, reason, active, added_by]
        async with self.pool.acquire() as conn:
            ret = await conn.fetchrow(query, *args)
            return (ret["id"], make_pattern(ret["pattern"], ret["pattern_type"]))

    async def delete(self, id: int) -> tuple[int, Pattern, str] | None:
        """
        delete an entry
        """
        query = """
            DELETE FROM mxbl
            WHERE id = $1
            RETURNING id, pattern, pattern_type, reason
        """
        async with self.pool.acquire() as conn:
            ret = await conn.fetchrow(query, id)
            return (ret["id"], make_pattern(ret["pattern"], ret["pattern_type"]), ret["reason"])

    async def edit_pattern(self, id: int, pattern: Pattern) -> tuple[int, Pattern] | None:
        """
        update the pattern of an entry
        """
        query = """
            UPDATE mxbl
            SET pattern = $2, pattern_type = $3
            WHERE id = $1
            RETURNING id, pattern, pattern_type
        """
        async with self.pool.acquire() as conn:
            ret = await conn.fetchrow(query, id, pattern.raw, pattern.ty)
            return (ret["id"], make_pattern(ret["pattern"], ret["pattern_type"]))

    async def edit_reason(self, id: int, reason: str) -> tuple[int, Pattern, str] | None:
        """
        update the reason of an entry
        """
        query = """
            UPDATE mxbl
            SET reason = $2
            WHERE id = $1
            RETURNING id, pattern, pattern_type, reason
        """
        async with self.pool.acquire() as conn:
            ret = await conn.fetchrow(query, id, reason)
            return (ret["id"], make_pattern(ret["pattern"], ret["pattern_type"]), ret["reason"])

    async def toggle(self, id: int) -> tuple[int, Pattern, bool] | None:
        """
        toggle a pattern active/warn by id
        """
        query = """
            UPDATE mxbl
            SET active = NOT active
            WHERE id = $1
            RETURNING id, pattern, pattern_type, active
        """
        async with self.pool.acquire() as conn:
            ret = await conn.fetchrow(query, id)
            return (ret["id"], make_pattern(ret["pattern"], ret["pattern_type"]), ret["active"])

    async def hit(self, id: int) -> int | None:
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
    async def get(self, name: str) -> Record | None:
        query = """
            SELECT name, value
            FROM settings
            WHERE name = $1
            LIMIT 1
        """
        async with self.pool.acquire() as conn:
            return await conn.fetchrow(query, name)

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

    async def set_(self, name: str, value: str) -> Record | None:
        query = """
            INSERT INTO settings
            (name, value)
            VALUES ($1, $2)
            ON CONFLICT(name)
            DO UPDATE SET
                value = EXCLUDED.value
            RETURNING name, value
        """
        async with self.pool.acquire() as conn:
            return await conn.fetchrow(query, name, value)


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
