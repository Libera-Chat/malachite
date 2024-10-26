import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass
class SaslConfig:
    user: str
    password: str

    @classmethod
    def from_toml(cls, toml: dict[str, str]):
        return cls(
            user=toml["user"],
            password=toml["pass"],
        )


@dataclass
class OperConfig:
    user: str
    password: str
    cert: Path
    key: Path

    @classmethod
    def from_toml(cls, toml: dict[str, str]):
        return cls(
            user=toml["user"],
            password=toml["pass"],
            cert=Path(toml["cert"]).resolve(),
            key=Path(toml["key"]).resolve(),
        )


@dataclass
class DatabaseConfig:
    user: str
    password: str | None
    host: str | None
    name: str

    @classmethod
    def from_toml(cls, toml: dict[str, str]):
        return cls(
            user=toml["user"],
            password=toml.get("pass"),
            host=toml.get("host"),
            name=toml["name"],
        )


@dataclass
class Config:
    server: str
    nickname: str
    username: str
    realname: str
    password: str | None
    channels: list[str]
    log: str | None

    sasl: SaslConfig
    oper: OperConfig
    database: DatabaseConfig

    timeout: float
    cache_ttl: int
    cache_size: int

    @classmethod
    def from_file(cls, fp: str | Path):
        fp = Path(fp)
        with fp.open('rb') as f:
            config_toml = tomllib.load(f)

        irc_toml = config_toml["irc"]
        settings_toml = config_toml.get("settings", dict())
        sasl = SaslConfig.from_toml(config_toml["sasl"])
        oper = OperConfig.from_toml(config_toml["oper"])
        database = DatabaseConfig.from_toml(config_toml["database"])

        return cls(
            server=irc_toml["server"],
            nickname=irc_toml["nickname"],
            username=irc_toml["username"],
            realname=irc_toml["realname"],
            password=irc_toml.get("pass"),
            channels=irc_toml["channels"],
            log=irc_toml.get("log"),
            sasl=sasl,
            oper=oper,
            database=database,
            timeout=settings_toml.get("timeout", 5),
            cache_ttl=settings_toml.get("cache_ttl", 24*60*60),
            cache_size=settings_toml.get("cache_size", 256),
        )
