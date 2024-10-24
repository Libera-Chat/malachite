import asyncio
import fnmatch
import ipaddress
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Self

import asyncpg
from asyncpg import Pool, Record

from .util import PatternType, pretty_delta, render_pattern


@dataclass
class MxblEntry:
    id: int
    pattern: str
    pattern_type: PatternType
    reason: str
    active: bool
    added: datetime
    added_by: str
    hits: int
    last_hit: datetime | None

    @classmethod
    def from_record(cls, rec: Record) -> Self:
        return cls(
            id=rec["id"],
            pattern=rec["pattern"],
            pattern_type=PatternType(rec["pattern_type"]),
            reason=rec["reason"],
            active=rec["active"],
            added=rec["added"],
            added_by=rec["added_by"],
            hits=rec["hits"],
            last_hit=rec["last_hit"],
        )

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
        pat = render_pattern(self.pattern, self.pattern_type)
        return (f"#{self.id}: \x02{pat}\x02 (\x1D{self.reason}\x1D) added {pretty_delta(now - self.added)}"
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
            SELECT id, pattern, pattern_type, reason, active, added, added_by, hits, last_hit
            FROM mxbl
            WHERE id = $1
        """
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(query, id)
        if row is not None:
            return MxblEntry.from_record(row)

    async def match(self, search: str) -> MxblEntry | None:
        """
        search all entries, return first match
        matches active entries first
        """
        rows = await self.list_all(order_by="active DESC, id")

        found = None
        for row in rows:
            match row.pattern_type:
                case PatternType.String:
                    # remove root domain . from both in case one doesn't have it
                    if row.pattern.rstrip(".") == search.rstrip("."):
                        found = row
                        break
                case PatternType.Glob:
                    if re.search(fnmatch.translate(row.pattern), search, flags=re.I):
                        found = row
                        break
                case PatternType.Regex:
                    if re.search(row.pattern, search, flags=re.I):
                        found = row
                        break
                case PatternType.Cidr:
                    try:
                        if ipaddress.ip_address(search) in ipaddress.ip_network(row.pattern):
                            found = row
                            break
                    except ValueError:
                        continue

        if found is not None:
            return found

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

    async def add(self, pattern: str, pattern_type: PatternType, reason: str, active: bool, added_by: str) -> Record | None:
        """
        add an entry
        """
        query = """
            INSERT INTO mxbl
            (pattern, pattern_type, reason, active, added, added_by)
            VALUES ($1, $2, $3, $4, NOW()::TIMESTAMP, $5)
            RETURNING id, pattern, pattern_type
        """
        args = [pattern, pattern_type, reason, active, added_by]
        async with self.pool.acquire() as conn:
            return await conn.fetchrow(query, *args)

    async def delete(self, id: int) -> Record | None:
        """
        delete an entry
        """
        query = """
            DELETE FROM mxbl
            WHERE id = $1
            RETURNING id, pattern, pattern_type, reason
        """
        async with self.pool.acquire() as conn:
            return await conn.fetchrow(query, id)

    async def edit_pattern(self, id: int, pattern: str, pattern_type: str) -> Record | None:
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
            return await conn.fetchrow(query, id, pattern, pattern_type)

    async def edit_reason(self, id: int, reason: str) -> Record | None:
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
            return await conn.fetchrow(query, id, reason)

    async def toggle(self, id: int) -> Record | None:
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
            return await conn.fetchrow(query, id)

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
