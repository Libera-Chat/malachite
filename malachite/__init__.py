import asyncio
import ipaddress

from dns.asyncresolver import Resolver
from dns.rdatatype import MX, A, AAAA

import ircrobots
from irctokens import build, Line
from ircstates.numerics import RPL_ISUPPORT, RPL_WELCOME, RPL_YOUREOPER

from .config import Config
from .database import Database
from .irc import Caller, command, on_message, Server

NICKSERV = "cattenoire"

__version__ = "0.1.0"


class MalachiteServer(Server):
    def __init__(self, bot: ircrobots.Bot, name: str, config: Config, database: Database):
        super().__init__(bot, name, config, database)
        self.resolver = Resolver()
        self.resolver.timeout = self._config.timeout
        self.resolver.lifetime = self._config.timeout

    # message handlers {{{

    @on_message(RPL_WELCOME)
    async def on_welcome(self, _):
        """oper up"""
        # self.send(build("OPER", [self._config.oper.user, self._config.oper.password]))
        ...

    @on_message(RPL_ISUPPORT)
    async def on_isupport(self, _):
        """finish initialisation and print a message to console"""
        if not self._init and self.isupport.network:
            print(f"[*] connected to {self.isupport.network} as {self.nickname}")
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
                resp = None

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
            drop = False # freeze instead
        else:
            return
        await self._check_domain(domain, account, drop)

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
        usage: ADD <ip|domain> <reason>
          add an ip or domain to the mxbl
        """
        try:
            pat = args[0]
        except IndexError:
            return "missing argument: <ip|domain>"
        try:
            reason = " ".join(args[1:])
        except IndexError:
            return "missing argument: <reason>"

        try:
            ipaddress.ip_address(pat)
        except ValueError:
            # not an ip address, must be a domain... ensure it's an FQDN
            if not pat.endswith("."):
                pat += "."

        id = await self.database.add(pat, reason, True, caller.oper)
        if id is not None:
            return f"added mxbl entry #{id}"
        return "adding mxbl entry failed"

    @command("DEL")
    async def _del(self, _: Caller, args: list[str]):
        """
        usage: DEL <id>
          remove an ip or domain from the mxbl
        """
        try:
            id = int(args[0])
        except ValueError:
            return "invalid id (not an integer)"
        except IndexError:
            return "missing argument: <id>"

        ret = await self.database.delete(id)
        if ret is not None:
            return f"removed mxbl entry #{ret}"
        return f"no entry found for id: {id}"

    @command("GET")
    async def _get(self, _: Caller, args: list[str]):
        """
        usage: GET <id>
          get information about a specific mxbl entry
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
        usage: LIST [limit = 0] [glob]
          list mxbl entries up to limit (default: no limit), optionally filtering with a glob pattern
        """
        try:
            limit = int(args[0])
        except ValueError:
            return "invalid limit (not an integer)"
        except IndexError:
            limit = 0
        try:
            search = args[1]
        except IndexError:
            search = "*"
        rows = await self.database.list_all(limit, search)
        if rows:
            return [str(r) for r in rows]
        return "no entries found"

    @command("TOGGLE")
    async def _toggle(self, _: Caller, args: list[str]):
        """
        usage: TOGGLE <id>
          enable or disable an entry
        """
        try:
            id = int(args[0])
        except ValueError:
            return "invalid id (not an integer)"
        except IndexError:
            return "missing argument: <id>"
        enabled = await self.database.toggle(id)
        if enabled is not None:
            en_str = "enabled" if enabled else "disabled"
            return f"mxbl entry #{id} was {en_str}"
        return f"no entry found for id: {id}"

    @command("EDITPATTERN")
    async def _edit_pattern(self, _: Caller, args: list[str]):
        """
        usage: EDITPATTERN <id> <ip|domain>
          update the ip or domain for a pattern by id
        """
        try:
            id = int(args[0])
        except ValueError:
            return "invalid id (not an integer)"
        except IndexError:
            return "missing argument: <id>"
        try:
            pat = args[1]
        except IndexError:
            return "missing argument: <ip|domain>"

        try:
            ipaddress.ip_address(pat)
        except ValueError:
            # not an ip address, must be a domain... ensure it's an FQDN
            if not pat.endswith("."):
                pat += "."

        id = await self.database.edit_pattern(id, pat)
        if id is not None:
            return f"updated mxbl entry #{id}"
        return "updating mxbl entry failed"

    @command("EDITREASON")
    async def _edit_reason(self, _: Caller, args: list[str]):
        """
        usage: EDITREASON <id> <reason>
          update the reason for a pattern by id
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

        id = await self.database.edit_reason(id, reason)
        if id is not None:
            return f"updated mxbl entry #{id}"
        return "updating mxbl entry failed"

    # }}}

    async def _check_domain(self, domain: str, account: str, drop: bool):
        """
        check if domain matches any pattern
        if not found, resolve MX, A, and AAAA for domain
        if MX points to domain, check it against patterns and resolve A and AAAA
        if any record matches any pattern, found
        if found: add *@domain to services badmail
            if new reg, fdrop and send notice
            if email change, freeze
        """
        if not (found := await self.database.find_active(domain)):
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

                        if (found := await self.database.find_active(rec_name)):
                            break
                    if found:
                        break

        if found:
            await self.database.hit(found.id)
            self.send_message(NICKSERV, f"BADMAIL ADD *@{domain} {found.full_reason}")
            if drop:
                self.send_message(NICKSERV, f"FDROP {account}")
            else:
                self.send_message(NICKSERV, (f"FREEZE {account} ON changed email to *@{domain} ({found.full_reason})"))

            whois = await self.send_whois(account)
            if whois:
                hostmask = f"{whois.nickname}!{whois.username}@{whois.hostname}"
            else:
                hostmask = "<Unknown user>"
            if drop:
                self.log(f"\x0305BAD\x03: {hostmask} registered {account} with \x02*@{domain}\x02"
                         f" (\x1D{found.full_reason}\x1D)")
            else:
                self.log(f"\x0305BAD\x03: {hostmask} changed email on {account} to \x02*@{domain}\x02"
                         f" (\x1D{found.full_reason}\x1D)")
            if drop:
                self.send(build("NOTICE", [
                    account, ("Your account has been dropped, please register it again with a valid email"
                              " address (no disposable/temporary email)")
                ]))


class Malachite(ircrobots.Bot):
    def __init__(self, config: Config, database: Database):
        super().__init__()
        self._config = config
        self._database = database

    def create_server(self, name: str):
        return MalachiteServer(self, name, self._config, self._database)
