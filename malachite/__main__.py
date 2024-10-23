import asyncio
from argparse import ArgumentParser

from ircrobots.params import ConnectionParams, SASLUserPass
from ircrobots.security import TLSVerifyChain

from . import Malachite
from .config import Config
from .database import Database


async def main(config: Config):
    database = await Database.connect(
        config.database.user,
        config.database.password,
        config.database.host,
        config.database.name,
    )
    bot = Malachite(config, database)

    params = ConnectionParams.from_hoststring(config.nickname, config.server)
    params.username = config.username
    params.realname = config.realname
    params.password = config.password
    params.sasl = SASLUserPass(config.sasl.user, config.sasl.password)
    params.tls = TLSVerifyChain(client_keypair=(str(config.oper.cert), str(config.oper.key)))

    autojoin = config.channels
    if config.log:
        autojoin.append(config.log)
    params.autojoin = autojoin

    await bot.add_server("malachite", params)
    await bot.run()


if __name__ == "__main__":
    parser = ArgumentParser()
    parser.add_argument("config")
    args = parser.parse_args()
    config = Config.from_file(args.config)
    asyncio.run(main(config))
