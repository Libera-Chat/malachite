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

    else:
        pat_ty = PatternType.String
        try:
            ipaddress.ip_address(pat)
        except ValueError:
            try:
                ipaddress.ip_network(pat)
                pat_ty = PatternType.Cidr
            except ValueError:
                # not an ip address or network, must be a domain... ensure it's an FQDN
                if not pat.endswith("."):
                    pat += "."

    return (pat, pat_ty)


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