import ipaddress
from datetime import timedelta
from enum import IntEnum

class PatternType(IntEnum):
    String = 0
    Glob = 1
    Regex = 2
    Cidr = 3


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

    return delim + pattern + delim + sfx


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
