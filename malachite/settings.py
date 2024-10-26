from .database import Database


class Settings:
    def __init__(self, database: Database) -> None:
        self._database = database
        self._settings = None

    async def load(self):
        self._settings = await self._database.get_all_settings()

    def all(self) -> dict[str, str]:
        if self._settings is None:
            raise ValueError("no settings loaded, run Settings.load()")
        return self._settings

    def __getattr__(self, attr) -> str | None:
        if self._settings is None:
            raise ValueError("no settings loaded, run Settings.load()")

        return self._settings.get(attr)

    async def set_(self, name, value) -> tuple[str, str] | None:
        if self._settings is None:
            await self.load()
        self._settings[name] = value  # type: ignore
        ret = await self._database.set_setting(name, value)
        if ret is not None:
            return tuple(ret)
