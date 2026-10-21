from __future__ import annotations

import asyncio
import logging
import sys

import discord
from discord.ext import commands

from bot.calls import Calls
from bot.config import load_settings

log = logging.getLogger("bot")


class CallBot(commands.Bot):
    def __init__(self, settings) -> None:
        intents = discord.Intents.default()
        super().__init__(command_prefix="!", intents=intents, help_command=None)
        self.settings = settings

    async def setup_hook(self) -> None:
        await self.add_cog(Calls(self))
        try:
            if self.settings.guild_id:
                guild = discord.Object(id=self.settings.guild_id)
                self.tree.copy_global_to(guild=guild)
                await self.tree.sync(guild=guild)
                log.info("Slash-команды синхронизированы для сервера %s", self.settings.guild_id)
            else:
                await self.tree.sync()
                log.info("Глобальные slash-команды синхронизированы (могут появиться с задержкой)")
        except discord.HTTPException:
            log.exception("Не удалось синхронизировать slash-команды")

    async def on_ready(self) -> None:
        log.info("Бот запущен: %s (id=%s), серверов: %d", self.user, self.user.id, len(self.guilds))


async def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except (AttributeError, OSError):
        pass

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("discord").setLevel(logging.WARNING)

    settings = load_settings()
    bot = CallBot(settings)
    async with bot:
        await bot.start(settings.token)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
