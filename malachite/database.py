import asyncio
from asyncio import Task
from dataclasses import dataclass
from typing import Sequence

import asyncpg
from asyncpg import Pool, Record

from .util import MxblEntry, Pattern, PatternStatus, make_pattern


@dataclass
class Table:
    pool: Pool


class MxblTable(Table):
    async def get(self, id: int) -> MxblEntry | None:
        """
        get one entry by id
        """
        query = """
            SELECT id, pattern, pattern_type, reason, status, added, added_by, hits, last_hit
            FROM mxbl
            WHERE id = $1
        """
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(query, id)
        if row is not None:
            return MxblEntry.from_record(row)

    async def list_(self, limit: int = 0, offset: int = 0, all: bool = False, order_by: str = "id") -> Sequence[MxblEntry]:
        """
        list all entries up to limit (optional, default all) from an offset (optional, default index 0)
        """
        if all:
            where = ""
        else:
            where = "WHERE status != 0"

        query = f"""
            SELECT id, pattern, pattern_type, reason, status, added, added_by, hits, last_hit
            FROM mxbl
            {where}
            ORDER BY {order_by}
            LIMIT $1
            OFFSET $2
        """
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query, limit or None, offset)
        return [MxblEntry.from_record(row) for row in rows]

    async def add(self, pattern: Pattern, reason: str, status: PatternStatus, added_by: str) -> tuple[int, Pattern] | None:
        """
        add an entry
        """
        query = """
            INSERT INTO mxbl
            (pattern, pattern_type, reason, status, added, added_by)
            VALUES ($1, $2, $3, $4, NOW()::TIMESTAMP, $5)
            RETURNING id, pattern, pattern_type
        """
        args = [pattern.raw, pattern.ty, reason, status, added_by]
        async with self.pool.acquire() as conn:
            if (ret := await conn.fetchrow(query, *args)) is not None:
                return (ret["id"], make_pattern(ret["pattern"], ret["pattern_type"]))

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
            if (ret := await conn.fetchrow(query, id, pattern.raw, pattern.ty)) is not None:
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
            if (ret := await conn.fetchrow(query, id, reason)) is not None:
                return (ret["id"], make_pattern(ret["pattern"], ret["pattern_type"]), ret["reason"])

    async def set_status(self, id: int, new: PatternStatus) -> tuple[int, Pattern, PatternStatus] | None:
        """
        set a pattern's status by id
        """
        # TODO
        query = """
            UPDATE mxbl
            SET status = $2
            WHERE id = $1
            RETURNING id, pattern, pattern_type, status
        """
        async with self.pool.acquire() as conn:
            if (ret := await conn.fetchrow(query, id, new)) is not None:
                return (ret["id"], make_pattern(ret["pattern"], ret["pattern_type"]), PatternStatus(ret["status"]))

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

    def get_all_settings(self):
        return asyncio.create_task(self.settings.get_all())

    def set_setting(self, name: str, value: str):
        return asyncio.create_task(self.settings.set_(name, value))

    def get(self, id: int) -> Task[MxblEntry | None]:
        return asyncio.create_task(self.mxbl.get(id))

    def list_(self, limit: int = 0, offset: int = 0, all: bool = False, order_by: str = "id") -> Task[Sequence[MxblEntry]]:
        return asyncio.create_task(self.mxbl.list_(limit, offset, all, order_by))

    def add(self, pattern: Pattern, reason: str, status: PatternStatus, added_by: str) -> Task[tuple[int, Pattern] | None]:
        return asyncio.create_task(self.mxbl.add(pattern, reason, status, added_by))

    def edit_pattern(self, id: int, pattern: Pattern) -> Task[tuple[int, Pattern] | None]:
        return asyncio.create_task(self.mxbl.edit_pattern(id, pattern))

    def edit_reason(self, id: int, reason: str) -> Task[tuple[int, Pattern, str] | None]:
        return asyncio.create_task(self.mxbl.edit_reason(id, reason))

    def set_status(self, id: int, new: PatternStatus) -> Task[tuple[int, Pattern, PatternStatus] | None]:
        return asyncio.create_task(self.mxbl.set_status(id, new))

    def hit(self, id: int) -> Task[int | None]:
        return asyncio.create_task(self.mxbl.hit(id))
