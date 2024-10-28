import asyncio

from cachetools import TTLCache
from dns.asyncresolver import Resolver
from dns.rdatatype import MX, A, AAAA

import ircrobots
from irctokens import build, Line
from ircstates.numerics import RPL_ISUPPORT, RPL_WELCOME, RPL_YOUREOPER

from .config import Config
from .database import Database
from .irc import Caller, command, on_message, Server
from .settings import Settings
from .util import match_patterns, MxblEntry, Pattern, parse_pattern

NICKSERV = "NickServ"

__version__ = "0.1.0"


class MalachiteServer(Server):
    def __init__(self, bot: ircrobots.Bot, name: str, config: Config, database: Database):
        super().__init__(bot, name, config, database)
        self.settings = Settings(database)

        self.resolver = Resolver()
        self.resolver.timeout = self._config.timeout
        self.resolver.lifetime = self._config.timeout

        self.cleanmails: TTLCache[str, bool] = TTLCache(maxsize=self._config.cache_size, ttl=self._config.cache_ttl)

    # message handlers {{{

    @on_message(RPL_WELCOME)
    async def on_welcome(self, _):
        """oper up"""
        self.send(build("OPER", [self._config.oper.user, self._config.oper.password]))

    @on_message(RPL_ISUPPORT)
    async def on_isupport(self, _):
        """finish initialisation and print a message to console"""
        if not self._init and self.isupport.network:
            print(f"[*] connected to {self.isupport.network} as {self.nickname}")
            await self.settings.load()
            self._init = True

    @on_message(RPL_YOUREOPER)
    async def on_youreoper(self, _):
        """disable snotes, they aren't necessary"""
        print("[*] opered up")
        self.send(build("MODE", [self.nickname, "-s"]))

    @on_message("PRIVMSG", lambda ln: ln.source is not None and len(ln.params) > 0 and ln.params[-1].startswith("\x01"))
    async def on_ctcp(self, line: Line):
        """respond to CTCP queries"""
        query = line.params[-1].strip("\x01").split()
        if not query:
            return
        command = query[0].upper()
        match command:
            case "VERSION":
                resp = f"VERSION malachite v{__version__}"
            case _:
                resp = ""

        if resp:
            self.send(build("NOTICE", [line.hostmask.nickname, f"\x01{resp}\x01"]))

    @on_message("PRIVMSG", lambda ln: ln.source is not None and ln.hostmask.nickname == NICKSERV)
    async def on_nickserv(self, line: Line):
        """parse and do actions upon NickServ messages"""
        msg = line.params[-1].split()
        if "REGISTER:" in msg:
            account = msg[0]
            domain = msg[-1].split("@")[1]
            drop = True
        elif "VERIFY:EMAILCHG:" in msg:
            account = msg[0]
            domain = msg[-1].split("@")[1].rstrip(")")
            drop = False  # freeze instead
        else:
            return

        if domain in self.cleanmails:
            return

        if (found := await self._check_domain(domain)) is not None:
            if not isinstance(found, MxblEntry):
                return  # should not ever happen
            await self.database.hit(found.id)
            if found.active and self.settings.pause == "0":
                self.send_message(NICKSERV, f"BADMAIL ADD *@{domain} {found.full_reason}")
                if drop:
                    self.send_message(NICKSERV, f"FDROP {account}")
                else:
                    self.send_message(NICKSERV,
                                      f"FREEZE {account} ON changed email to *@{domain} ({found.full_reason})")

            whois = await self.send_whois(account)
            if whois:
                hostmask = f"{whois.nickname}!{whois.username}@{whois.hostname}"
            else:
                hostmask = "<unknown user>"

            if found.active and self.settings.pause == "0":
                if drop:
                    self.log(f"\x0305BAD\x03: {hostmask} registered {account} with \x02*@{domain}\x02"
                             f" (\x1D{found.full_reason}\x1D)")
                    self.send(build("NOTICE", [
                        account, ("Your account has been dropped, please register it again with a valid email"
                                  " address (no disposable/temporary email)")
                    ]))
                else:
                    self.log(f"\x0305BAD\x03: {hostmask} changed email on {account} to \x02*@{domain}\x02"
                             f" (\x1D{found.full_reason}\x1D)")
            else:
                if drop:
                    self.log(f"\x0307WARN\x03: {hostmask} registered {account} with \x02*@{domain}\x02"
                             f" (\x1D{found.full_reason}\x1D)")
                else:
                    self.log(f"\x0307WARN\x03: {hostmask} changed email on {account} to \x02*@{domain}\x02"
                             f" (\x1D{found.full_reason}\x1D)")
        else:
            self.cleanmails[domain] = True

    # }}}

    # command handlers {{{

    @command("HELP")
    async def _help(self, _: Caller, args: list[str]):
        """
        usage: HELP [command]
          show usage information about a command
        """
        if not args:
            return self._cmd_handlers["help"].help + "\n  available commands: " + ", ".join(self._cmd_handlers.keys())

        cmd = args[0].lower()
        try:
            return self._cmd_handlers[cmd].help
        except KeyError:
            return f"unknown command '{cmd}'"

    @command("ADD")
    async def _add(self, caller: Caller, args: list[str]):
        """
        usage: ADD <ip|cidr|domain|%glob%|/regex/> <reason>
          add a pattern to the mxbl. globs and regexes are case-insensitive
        """
        try:
            pat = parse_pattern(args[0])
        except IndexError:
            return "missing argument: <ip|domain>"
        except ValueError as e:
            return f"error: {e}"
        try:
            reason = " ".join(args[1:])
        except IndexError:
            return "missing argument: <reason>"

        await self.cache_evict_by_pattern(pat)

        ret = await self.database.add(pat, reason, True, caller.oper)
        if ret is not None:
            id, pat = ret
            self.log(f"{caller.nick} ({caller.oper}) ADD: added pattern {id} \x02{pat}\x02 ({reason})")
            return f"added mxbl entry #{id}"
        return "adding mxbl entry failed"

    @command("DEL")
    async def _del(self, caller: Caller, args: list[str]):
        """
        usage: DEL <id>
          remove a pattern from the mxbl
        """
        try:
            id = int(args[0])
        except ValueError:
            return "invalid id (not an integer)"
        except IndexError:
            return "missing argument: <id>"

        ret = await self.database.delete(id)
        if ret is not None:
            id, pat, reason = ret
            self.log(f"{caller.nick} ({caller.oper}) DEL: deleted pattern {id} \x02{pat}\x02 ({reason})")
            return f"removed mxbl entry #{id}"
        return f"no entry found for id: {id}"

    @command("GET")
    async def _get(self, _: Caller, args: list[str]):
        """
        usage: GET <id>
          get information about an entry
        """
        try:
            id = int(args[0])
        except ValueError:
            return "invalid id (not an integer)"
        except IndexError:
            return "missing argument: <id>"

        ret = await self.database.get(id)
        if ret is not None:
            return str(ret)
        return f"no entry found for id: {id}"

    @command("LIST")
    async def _list(self, _: Caller, args: list[str]):
        """
        usage: LIST [limit = 0] [offset = 0]
          list mxbl entries up to limit (default: no limit), starting at offset (default: index 0)
        """
        try:
            limit = int(args[0])
            if limit < 0:
                raise ValueError
        except ValueError:
            return "invalid limit (not an integer >= 0)"
        except IndexError:
            limit = 0
        try:
            offset = int(args[1])
            if offset < 0:
                raise ValueError
        except ValueError:
            return "invalid offset (not an integer >= 0)"
        except IndexError:
            offset = 0
        rows = await self.database.list_all(limit, offset)
        if rows:
            return [str(r) for r in rows]
        return "no entries found"

    @command("TOGGLE")
    async def _toggle(self, caller: Caller, args: list[str]):
        """
        usage: TOGGLE <id>
          make an entry active or warn
        """
        try:
            id = int(args[0])
        except ValueError:
            return "invalid id (not an integer)"
        except IndexError:
            return "missing argument: <id>"
        ret = await self.database.toggle(id)
        if ret is not None:
            id, pat, active = ret
            old, new = ("WARN", "ACTIVE") if active else ("ACTIVE", "WARN")
            self.log(f"{caller.nick} ({caller.oper}) TOGGLE: toggled pattern {id} \x02{pat}\x02: {old} -> {new}")
            return f"mxbl entry #{id} {old} -> {new}"
        return f"no entry found for id: {id}"

    @command("EDITPATTERN")
    async def _edit_pattern(self, caller: Caller, args: list[str]):
        """
        usage: EDITPATTERN <id> <ip|cidr|domain|%glob%|/regex/>
          update the pattern of an entry by id
        """
        try:
            id = int(args[0])
        except ValueError:
            return "invalid id (not an integer)"
        except IndexError:
            return "missing argument: <id>"
        try:
            pat = parse_pattern(args[1])
        except IndexError:
            return "missing argument: <ip|domain>"
        except ValueError as e:
            return f"error: {e}"

        await self.cache_evict_by_pattern(pat)

        ret = await self.database.edit_pattern(id, pat)
        if ret is not None:
            id, pat = ret
            self.log(f"{caller.nick} ({caller.oper}) EDITPATTERN: updated pattern {id} to \x02{pat}\x02")
            return f"updated mxbl entry #{id}"
        return "updating mxbl entry failed"

    @command("EDITREASON")
    async def _edit_reason(self, caller: Caller, args: list[str]):
        """
        usage: EDITREASON <id> <reason>
          update the reason for an entry by id
        """
        try:
            id = int(args[0])
        except ValueError:
            return "invalid id (not an integer)"
        except IndexError:
            return "missing argument: <id>"
        try:
            reason = " ".join(args[1:])
        except IndexError:
            return "missing argument: <reason>"

        ret = await self.database.edit_reason(id, reason)
        if ret is not None:
            id, pat, reason = ret
            self.log(f"{caller.nick} ({caller.oper}) EDITREASON: updated pattern {id} \x02{pat}\x02 reason: {reason}")
            return f"updated mxbl entry #{id}"
        return "updating mxbl entry failed"

    @command("SETTINGS")
    async def _settings(self, caller: Caller, args: list[str]):
        """
        usage: SETTINGS <GET|GETALL|SET> [name] [value]
          update dynamic settings for the bot
        """
        try:
            subcommand = args[0].upper()
        except IndexError:
            return "missing argument: subcommand <GET|GETALL|SET>"

        match subcommand:
            case "GET":
                try:
                    name = args[1].lower()
                except IndexError:
                    return "missing argument: <name>"
                try:
                    return f"{name}: {getattr(self.settings, name)!r}"
                except ValueError:
                    await self.settings.load()
                    return f"{name}: {getattr(self.settings, name)!r}"
            case "GETALL":
                try:
                    return [f"{n}: {v!r}" for n, v in self.settings.all().items()]
                except ValueError:
                    await self.settings.load()
                    return [f"{n}: {v!r}" for n, v in self.settings.all().items()]
            case "SET":
                try:
                    name = args[1].lower()
                except IndexError:
                    return "missing argument: <name>"
                try:
                    value = args[2]
                except IndexError:
                    return "missing argument: <value>"
                ret = await self.settings.set_(name, value)
                if ret is not None:
                    name, value = ret
                    self.log(f"{caller.nick} ({caller.oper}) SETTINGS: set {name} to {value!r}")
                    return f"set {name} to {value!r}"
                else:
                    return f"failed to set {name} to {value!r}"
            case _:
                return f"invalid subcommand {subcommand}"

    @command("TEST")
    async def _testmatch(self, _: Caller, args: list[str]):
        """
        usage: TEST <email|domain>
          test if an email or domain would match an existing pattern
        """
        try:
            _, _, domain = args[0].rpartition("@")  # type: ignore
        except IndexError:
            return "missing argument: <email|domain>"

        found = await self._check_domain(domain)

        if found:
            return f"match: {found}"
        return "does not match any mxbl entries"

    @command("TESTPAT")
    async def _testpattern(self, _: Caller, args: list[str]):
        """
        usage: TESTPAT <ip|cidr|domain|%glob%|/regex/> <email|domain>
          test if an email or domain would match a specified pattern
        """
        try:
            pat = parse_pattern(args[0])
        except IndexError:
            return "missing argument: <ip|cidr|domain|%glob%|/regex/>"
        try:
            _, _, domain = args[1].rpartition("@")  # type: ignore
        except IndexError:
            return "missing argument: <email|domain>"

        found = await self._check_domain(domain, pat)

        if found:
            return f"{domain} matches \x02{found}\x02"
        return "does not match"

    @command("CACHE")
    async def _showcache(self, _: Caller, args: list[str]):
        """
        usage: CACHE <SHOW|DEL> [name]
          view or modify the clean domain cache
        """
        try:
            subcommand = args[0].upper()
        except IndexError:
            return "missing argument: subcommand <SHOW|DEL>"

        match subcommand:
            case "DEL":
                try:
                    name = args[1].lower()
                except IndexError:
                    return "missing argument: <name>"
                if name in self.cleanmails:
                    del self.cleanmails[name]
                    return f"removed {name} from clean domain cache"
                else:
                    return f"{name} not cached"
            case "SHOW":
                cache = list(self.cleanmails.keys())
                return [", ".join(cache[i:i+8]) for i in range(0, len(cache), 8)]
            case _:
                return f"invalid subcommand {subcommand}"

    # }}}

    async def _check_domain(self, domain: str, pattern: Pattern | None = None) -> MxblEntry | Pattern | None:
        """
        check if domain matches any entry
        if not found, resolve MX, A, and AAAA for domain
        if MX points to domain, check it against entries and resolve A and AAAA
        if any record matches any entry, found
        if found: add *@domain to services badmail
            if new reg, fdrop and send notice
            if email change, freeze
        """
        patterns: list[MxblEntry | Pattern]
        if pattern is not None:
            patterns = [pattern]
        else:
            # get all patterns, active entries first
            patterns = await self.database.list_all(order_by="active DESC, id")

        if not (found := match_patterns(patterns, domain)):
            queue = [(domain, MX), (domain, A), (domain, AAAA)]
            while queue:
                domain, ty = queue.pop(0)
                try:
                    resp = await asyncio.create_task(self.resolver.resolve(qname=domain, rdtype=ty))
                except Exception:
                    pass
                else:
                    for rec in resp:
                        if rec.rdtype == MX:
                            rec_name = rec.exchange.to_text()  # type: ignore
                            queue.insert(0, (rec_name, AAAA))
                            queue.insert(0, (rec_name, A))
                        elif rec.rdtype in (A, AAAA):
                            rec_name = rec.address  # type: ignore
                        else:
                            continue

                        if (found := match_patterns(patterns, rec_name)):
                            break
                    if found:
                        break

        return found

    async def cache_evict_by_pattern(self, pattern: Pattern):
        for domain in self.cleanmails:
            if await asyncio.create_task(self._check_domain(domain, pattern)) is not None:
                del self.cleanmails[domain]


class Malachite(ircrobots.Bot):
    def __init__(self, config: Config, database: Database):
        super().__init__()
        self._config = config
        self._database = database

    def create_server(self, name: str):
        return MalachiteServer(self, name, self._config, self._database)
