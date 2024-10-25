import fnmatch
import ipaddress
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, UTC
from enum import IntEnum
from typing import Self

from asyncpg import Record


class PatternType(IntEnum):
    String = 0
    Glob = 1
    Regex = 2
    Cidr = 3
    IpAddr = 4


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

    @classmethod
    def from_pattern(cls, pattern: str, pattern_type: PatternType | None = None) -> Self:
        if pattern_type is None:
            pattern, pattern_type = parse_pattern(pattern)
        return cls(
            id=-1,
            pattern=pattern,
            pattern_type=pattern_type,
            reason="",
            active=False,
            added=datetime.now(UTC),
            added_by="",
            hits=0,
            last_hit=None,
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
        return (f"#{self.id}: \x02{self.render_pattern()}\x02 (\x1D{self.reason}\x1D) added {pretty_delta(now - self.added)}"
                f" by \x02{self.added_by}\x02 with \x02{self.hits}\x02 hits (last hit: {last_hit}) [{active}]")

    def render_pattern(self) -> str:
        return render_pattern(self.pattern, self.pattern_type)

    @property
    def full_reason(self) -> str:
        return f"mxbl #{self.id} - {self.reason}"



def parse_pattern(pat: str) -> tuple[str, PatternType]:
    if pat.startswith("%") and pat.endswith("%"):
        pat = pat.removeprefix("%").removesuffix("%")
        pat_ty = PatternType.Glob

    elif pat.startswith("/") and pat.endswith("/"):
        pat = pat.removeprefix("/").removesuffix("/")
        pat_ty = PatternType.Regex

    elif "/" in pat:
        try:
            ipaddress.ip_network(pat)
            pat_ty = PatternType.Cidr
        except ValueError:
            pat_ty = PatternType.String

    else:
        try:
            ipaddress.ip_address(pat)
            pat_ty = PatternType.IpAddr
        except ValueError:
            pat_ty = PatternType.String

    return (pat, pat_ty)


def render_pattern(pattern, pattern_type) -> str:
    delim = ""
    sfx = ""

    match pattern_type:
        case PatternType.Glob:
            delim = "%"
        case PatternType.Regex:
            delim = "/"
        case PatternType.String:
            delim = "'"
        case PatternType.Cidr:
            delim = ""
            sfx = " [CIDR]"
        case PatternType.IpAddr:
            delim = ""
            sfx = " [IP]"

    return delim + pattern + delim + sfx


def match_patterns(patterns: list[MxblEntry], search: str) -> MxblEntry | None:
    for pat in patterns:
        match pat.pattern_type:
            case PatternType.String:
                # remove root domain . from both in case one doesn't have it
                if pat.pattern.rstrip(".") == search.rstrip("."):
                    return pat
            case PatternType.Glob:
                if re.search(fnmatch.translate(pat.pattern), search, flags=re.I):
                    return pat
            case PatternType.Regex:
                if re.search(pat.pattern, search, flags=re.I):
                    return pat
            case PatternType.Cidr:
                try:
                    if ipaddress.ip_address(search) in ipaddress.ip_network(pat.pattern):
                        return pat
                except ValueError:
                    continue
            case PatternType.IpAddr:
                try:
                    if ipaddress.ip_address(search) == ipaddress.ip_address(pat.pattern):
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
