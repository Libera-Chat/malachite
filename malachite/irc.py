import asyncio
import inspect
import shlex
from dataclasses import dataclass
from typing import Any, Callable, Coroutine

import ircrobots
from ircrobots import ircv3
from irctokens import build, Line

from .config import Config
from .database import Database

CAP_OPER = ircv3.Capability(None, "solanum.chat/oper")


@dataclass
class Caller:
    nick: str
    source: str
    oper: str


type MsgHandler = Callable[[Any, Line], Coroutine[Any, Any, None]]

class OnMessage:
    def __init__(self, command: str, predicate: Callable[[Line], bool] | None = None):
        self.command = command.upper()
        self.predicate = predicate if predicate is not None else lambda _: True

    def __call__(self, handler):
        self.handler = handler
        self.name = handler.__name__
        return self

    def run(self, cls: ircrobots.Server, line: Line):
        return self.handler(cls, line)

    def __repr__(self) -> str:
        return f"<message handler {self.name!r} for {self.command!r}>"

on_message = OnMessage


type CmdHandler = Callable[[Any, Caller, list[str] | str], Coroutine[Any, Any, str]]

class Command:
    def __init__(self, name: str):
        self.name = name.lower()

    def __call__(self, handler):
        self.handler = handler
        self.help = inspect.getdoc(self.handler) or f"no help available for '{self.name}'"
        return self

    def run(self, cls: ircrobots.Server, caller: Caller, args: list[str]):
        return self.handler(cls, caller, args)

    def __repr__(self) -> str:
        return f"<command handler for {self.name!r}>"

command = Command


class Server(ircrobots.Server):
    database: Database

    def __init__(self, bot: ircrobots.Bot, name: str, config: Config, database: Database):
        super().__init__(bot, name)
        self.desired_caps.add(CAP_OPER)
        self._init = False
        self._config = config
        self.database = database
        self._cmd_handlers = {
            v.name.lower(): v for _, v in
            inspect.getmembers(type(self), predicate=lambda m: isinstance(m, Command))
        }
        self._msg_handlers = [h for _, h in inspect.getmembers(type(self), predicate=lambda m: isinstance(m, OnMessage))]

        print("[*] registered command handlers:")
        print("\t" + ", ".join(self._cmd_handlers.keys()))
        print("[*] registered message handlers:")
        for h in self._msg_handlers:
            print(f"\t{h.command} => {h.name}")

    def set_throttle(self, rate: int, time: float):
        # turn off throttling
        pass

    async def log(self, text: str):
        if self._config.log:
            await self.send_message(self._config.log, text)

    async def line_read(self, line: Line):
        handlers = [h for h in self._msg_handlers
                    if line.command == h.command and h.predicate(line)]
        ret = await asyncio.gather(*(h.run(self, line) for h in handlers), return_exceptions=True)
        for i, e in enumerate(ret):
            if e is not None:
                print(f"[!] exception encountered in message handler {handlers[i].name!r}: {e}")

    @on_message("PRIVMSG", lambda ln: ln.source is not None)
    async def on_command(self, line: Line):
        if self.is_me(line.hostmask.nickname):
            return

        first, _, rest = line.params[1].partition(" ")

        if self.is_me(line.params[0]):
            # private message
            target = line.hostmask.nickname
            command = first
            sargs = rest

        elif rest and first in {f"{self.nickname}{c}" for c in [":", ",", ""]}:
            # highlight in channel
            command, _, sargs = rest.partition(" ")
            target = line.params[0]

        else:
            return

        if not line.tags or not (oper := line.tags.get("solanum.chat/oper", "")):
            # TODO
            # return
            oper = "yeah"

        caller = Caller(line.hostmask.nickname, str(line.hostmask), oper)

        command = command.lower()
        if command not in self._cmd_handlers.keys():
            return

        try:
            args = shlex.split(sargs)
        except ValueError as e:
            await self.send(build("NOTICE", [target, f"shlex failure: {str(e)}"]))
            return

        try:
            outs = await self._cmd_handlers[command].run(self, caller, args)
        except Exception as e:
            print(f"[!] exception encountered in command handler {command!r}: {e}")
        else:
            if isinstance(outs, str):
                outs = outs.splitlines()
            for out in outs:
                await self.send(build("NOTICE", [target, out]))
