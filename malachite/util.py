import fnmatch
import ipaddress
import re
from abc import ABC
from dataclasses import dataclass
from datetime import datetime, timedelta, UTC
from enum import IntEnum
from typing import Any, Self

from asyncpg import Record


class PatternType(IntEnum):
    Domain = 0
    Glob = 1
    Regex = 2
    Cidr = 3
    IpAddr = 4


class Pattern(ABC):
    __slots__ = ("raw", "pattern", "ty", "_delim", "_sfx")

    def __init__(self, pattern: str):
        self.raw = pattern
        self.pattern: Any = None
        self.ty = getattr(PatternType, type(self).__name__)
        self._delim = ""

    def __str__(self) -> str:
        return self._delim + self.raw + self._delim

    def __repr__(self) -> str:
        return f"<{self.ty.name} pattern {self.pattern!r} (raw: {self.raw!r})>"


class Domain(Pattern):
    def __init__(self, pattern: str):
        super().__init__(pattern)
        self.pattern = pattern.rstrip(".")
        self._delim = "'"

    def __eq__(self, value: str) -> bool:  # type: ignore
        # remove root domain . for comparison
        return self.pattern == value.rstrip(".")


class Glob(Pattern):
    def __init__(self, pattern: str):
        super().__init__(pattern)
        self.pattern = re.compile(fnmatch.translate(pattern), flags=re.I)
        self._delim = "%"

    def __eq__(self, value: str) -> bool:  # type: ignore
        return self.pattern.search(value) is not None


class Regex(Pattern):
    def __init__(self, pattern: str):
        super().__init__(pattern)
        self.pattern = re.compile(pattern, flags=re.I)
        self._delim = "/"

    def __eq__(self, value: str) -> bool:  # type: ignore
        return self.pattern.search(value) is not None


class Cidr(Pattern):
    def __init__(self, pattern: str):
        super().__init__(pattern)
        self.pattern = ipaddress.ip_network(pattern)

    def __eq__(self, value: str) -> bool:  # type: ignore
        try:
            return ipaddress.ip_address(value) in self.pattern
        except ValueError:
            return super().__eq__(value)


class IpAddr(Pattern):
    def __init__(self, pattern: str):
        super().__init__(pattern)
        self.pattern = ipaddress.ip_address(pattern)

    def __eq__(self, value: str) -> bool:  # type: ignore
        try:
            return self.pattern == ipaddress.ip_address(value)
        except ValueError:
            return False


@dataclass
class MxblEntry:
    id: int
    pattern: Pattern
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
            pattern=make_pattern(rec["pattern"], rec["pattern_type"]),
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
            last = now - self.last_hit
            if last.total_seconds() < (6 * 60 * 60):
                last_hit = f"\x0307{pretty_delta(last)}\x03"
            else:
                last_hit = pretty_delta(last)
        else:
            last_hit = "\x0312never\x03"
        active = "\x0313ACTIVE\x03" if self.active else "\x0311WARN\x03"
        return (f"#{self.id}: \x02{self.pattern}\x02 (\x1D{self.reason}\x1D) added {pretty_delta(now - self.added)}"
                f" by \x02{self.added_by}\x02 with \x02{self.hits}\x02 hits (last hit: {last_hit}) [{active}]")

    @property
    def full_reason(self) -> str:
        return f"mxbl #{self.id} - {self.reason}"


def make_pattern(pat: str, ty: PatternType) -> Pattern:
    match ty:
        case PatternType.Domain:
            return Domain(pat)
        case PatternType.Glob:
            return Glob(pat)
        case PatternType.Regex:
            return Regex(pat)
        case PatternType.Cidr:
            return Cidr(pat)
        case PatternType.IpAddr:
            return IpAddr(pat)


def parse_pattern(pat: str) -> Pattern:
    if pat.startswith("%") and pat.endswith("%"):
        return Glob(pat.removeprefix("%").removesuffix("%"))

    elif pat.startswith("/") and pat.endswith("/"):
        return Regex(pat.removeprefix("/").removesuffix("/"))

    elif "/" in pat:
        try:
            return Cidr(pat)
        except ValueError:
            raise ValueError("invalid pattern")

    else:
        try:
            return IpAddr(pat)
        except ValueError:
            return Domain(pat)


def match_patterns(patterns: list[MxblEntry | Pattern], search: str) -> MxblEntry | Pattern | None:
    for pat in patterns:
        try:
            if isinstance(pat, MxblEntry):
                if pat.pattern == search:
                    return pat
            elif isinstance(pat, Pattern):
                if pat == search:
                    return pat
        except ValueError:
            continue


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
