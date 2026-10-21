"""Cog с логикой вызовов: публикация карточки, отклики, закрытие."""

from __future__ import annotations

import asyncio
import io
import logging
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands
from PIL import Image

from .card import CardData, render_card
from .config import Settings
from .db import Database
from .ui import MAX_OPEN_CALLS, CallView, Draft, NewCallModal, PanelView, PublishError

log = logging.getLogger(__name__)


async def load_avatar(user: discord.abc.User) -> Image.Image | None:
    try:
        data = await user.display_avatar.replace(size=256, static_format="png").read()
        return Image.open(io.BytesIO(data)).convert("RGBA")
    except Exception:
        log.debug("Не удалось загрузить аватар %s", getattr(user, "id", "?"), exc_info=True)
        return None


class Calls(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.settings: Settings = bot.settings  # type: ignore[attr-defined]
        self.db = Database(self.settings.db_path)
        self.log = log

    # ------------------------------------------------------------- lifecycle
    async def cog_load(self) -> None:
        await self.db.init()
        active = await self.db.open_calls()
        for call in active:
            self.bot.add_view(CallView(self, call), message_id=int(call["message_id"]))
        self.bot.add_view(PanelView(self))
        log.info("Хранилище готово, активных вызовов: %d", len(active))

    @commands.Cog.listener()
    async def on_raw_message_delete(self, payload: discord.RawMessageDeleteEvent) -> None:
        """Если карточку удалили вручную — освобождаем слот автора."""
        try:
            await self.db.close_by_message(payload.message_id)
        except Exception:
            log.warning("Не удалось закрыть вызов по удалённому сообщению", exc_info=True)

    # -------------------------------------------------------------- commands
    @app_commands.command(name="panel", description="Опубликовать панель создания вызовов")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    async def panel(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        channel = interaction.channel
        if channel is None or not isinstance(channel, discord.abc.Messageable):
            await interaction.edit_original_response(content="⚠️ Здесь нельзя отправить панель.")
            return

        target = (
            f"<#{self.settings.calls_channel_id}>"
            if self.settings.calls_channel_id
            else "канал вызовов (задай `CALLS_CHANNEL_ID`)"
        )
        embed = discord.Embed(
            title="🎫 Вызовы на КВ",
            description=(
                "**Как это работает**\n"
                "1. Нажми кнопку ниже и заполни тикет: заголовок, MMR, время матча.\n"
                "2. Проверь карточку, выбери сервер и режим.\n"
                f"3. Бот опубликует вызов в {target} и создаст ветку для откликов.\n\n"
                "Откликнуться может любой участник — кнопка **«Принять вызов»** под карточкой."
            ),
            color=self.settings.accent_color,
        )
        embed.set_footer(text=f"{self.settings.brand_name} · {self.settings.brand_note}")

        await channel.send(embed=embed, view=PanelView(self))
        await interaction.edit_original_response(content="✅ Панель вызовов отправлена.")

    @app_commands.command(name="call", description="Создать вызов на КВ")
    @app_commands.guild_only()
    async def call(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(NewCallModal(self))

    # --------------------------------------------------------------- publish
    async def publish(self, interaction: discord.Interaction, draft: Draft) -> discord.Message:
        settings = self.settings
        if not settings.calls_channel_id:
            raise PublishError("Не задан `CALLS_CHANNEL_ID` в `.env` — некуда публиковать вызовы.")

        channel = self.bot.get_channel(settings.calls_channel_id)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(settings.calls_channel_id)
            except discord.HTTPException as error:
                raise PublishError("Канал вызовов не найден. Проверь `CALLS_CHANNEL_ID`.") from error
        if not isinstance(channel, discord.abc.Messageable):
            raise PublishError("`CALLS_CHANNEL_ID` указывает не на текстовый канал.")

        user = interaction.user
        active = await self.db.count_open_calls(user.id)
        if active >= MAX_OPEN_CALLS:
            raise PublishError(
                f"У тебя уже {active} активных вызова. Закрой один из них, чтобы создать новый."
            )

        call_id = await self.db.create_call(
            {
                "guild_id": interaction.guild_id,
                "author_id": user.id,
                "author_name": user.name,
                "author_display": user.display_name,
                "author_avatar": user.display_avatar.url,
                "quote": draft.quote,
                "mmr": draft.mmr,
                "time_text": draft.time_text,
                "server": draft.server,
                "mode": draft.mode,
                "comment": draft.comment or None,
            }
        )
        call = await self.db.get_call(call_id)
        if call is None:
            raise PublishError("Не удалось сохранить вызов. Попробуй ещё раз.")

        try:
            card = await self.render_card(call)
            message = await channel.send(
                content=self.build_content(call),
                file=discord.File(io.BytesIO(card), filename="call.png"),
                view=CallView(self, call),
                allowed_mentions=self.allowed_mentions(),
            )
        except discord.HTTPException as error:
            log.exception("Не удалось отправить карточку вызова %s", call_id)
            await self.db.set_status(call_id, "failed")
            raise PublishError(
                "Не удалось отправить карточку. Проверь права бота в канале вызовов."
            ) from error
        except Exception as error:
            log.exception("Не удалось собрать карточку вызова %s", call_id)
            await self.db.set_status(call_id, "failed")
            raise PublishError(
                "Не удалось собрать карточку. Проверь настройки шрифтов и `CARD_ACCENT`."
            ) from error

        thread: discord.Thread | None = None
        try:
            thread = await message.create_thread(
                name=self.thread_name(call),
                auto_archive_duration=1440,
            )
        except discord.HTTPException:
            log.warning("Не удалось создать ветку для вызова %s", call_id, exc_info=True)

        await self.db.attach_message(
            call_id,
            message.channel.id,
            message.id,
            thread.id if thread is not None else None,
        )

        if thread is not None:
            try:
                await thread.add_user(user)
            except discord.HTTPException:
                pass
            try:
                await thread.send(
                    content=f"<@{user.id}>",
                    embed=self.thread_intro(call),
                    allowed_mentions=discord.AllowedMentions(users=True),
                )
            except discord.HTTPException:
                log.warning("Не удалось отправить приветствие в ветку %s", thread.id, exc_info=True)

        return message

    # ---------------------------------------------------------------- accept
    async def accept_call(
        self,
        interaction: discord.Interaction,
        call_id: int,
        team_level: str,
        note: str,
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        call = await self.db.get_call(call_id)
        if call is None or call["status"] != "open":
            await interaction.edit_original_response(content="⚠️ Этот вызов уже закрыт.")
            return
        if int(call["author_id"]) == interaction.user.id:
            await interaction.edit_original_response(content="⚠️ Нельзя принять собственный вызов.")
            return
        if await self.db.get_response(call_id, interaction.user.id):
            await interaction.edit_original_response(content="⚠️ Ты уже откликнулся на этот вызов.")
            return

        responder = interaction.user
        await self.db.add_response(
            call_id,
            responder.id,
            responder.name,
            team_level or None,
            note or None,
        )

        thread = await self.get_thread(call)
        posted_in_thread = False
        if thread is not None:
            embed = discord.Embed(
                title="🤝 Отклик на вызов",
                color=0x3BA55D,
                description=f"«{call['quote']}»",
            )
            embed.set_author(name=responder.display_name, icon_url=responder.display_avatar.url)
            embed.add_field(name="Игрок", value=f"{responder.mention} · `{responder.name}`", inline=False)
            if team_level:
                embed.add_field(name="Уровень команды", value=team_level[:1024], inline=True)
            if note:
                embed.add_field(name="Запись", value=note[:1024], inline=False)
            embed.set_footer(text="Автор вызова получил уведомление в ЛС")
            try:
                await thread.send(
                    content=f"<@{call['author_id']}>",
                    embed=embed,
                    allowed_mentions=discord.AllowedMentions(users=True),
                )
                posted_in_thread = True
            except discord.HTTPException:
                log.warning("Не удалось написать в ветку вызова %s", call_id, exc_info=True)

        dm_sent = await self.dm_author(call, responder, team_level, note, thread)

        lines = ["✅ Отклик отправлен."]
        if thread is not None:
            lines.append(f"[Открыть ветку вызова]({thread.jump_url})")
        if not dm_sent:
            lines.append("-# Автор закрыл личные сообщения — отклик сохранён в ветке.")
        if not posted_in_thread:
            lines.append("-# Ветка недоступна, но автор получил уведомление.")
        await interaction.edit_original_response(content="\n".join(lines))

    async def dm_author(
        self,
        call: dict[str, Any],
        responder: discord.abc.User,
        team_level: str,
        note: str,
        thread: discord.Thread | None,
    ) -> bool:
        try:
            author = self.bot.get_user(int(call["author_id"])) or await self.bot.fetch_user(
                int(call["author_id"])
            )
        except discord.HTTPException:
            return False

        embed = discord.Embed(
            title="🤝 Твой вызов приняли",
            color=self.settings.accent_color,
            description=f"«{call['quote']}»",
        )
        embed.add_field(
            name="Игрок",
            value=f"**{responder.display_name}**\n`{responder.name}`",
            inline=True,
        )
        embed.add_field(name="Уровень команды", value=team_level or "не указан", inline=True)
        if note:
            embed.add_field(name="Запись", value=note[:1024], inline=False)
        embed.set_thumbnail(url=responder.display_avatar.url)
        if thread is not None:
            embed.add_field(name="Ветка вызова", value=thread.jump_url, inline=False)
        embed.set_footer(text="Ответь игроку в личных сообщениях, чтобы договориться")

        view: discord.ui.View | None = None
        if thread is not None:
            view = discord.ui.View()
            view.add_item(discord.ui.Button(label="Открыть ветку", emoji="🧵", url=thread.jump_url))

        try:
            await author.send(embed=embed, view=view)
            return True
        except discord.HTTPException:
            return False

    # ----------------------------------------------------------------- close
    async def close_call(self, interaction: discord.Interaction, call_id: int) -> None:
        call = await self.db.get_call(call_id)
        if call is None or call["status"] != "open":
            await interaction.response.send_message("Этот вызов уже закрыт.", ephemeral=True)
            return

        member = interaction.user if isinstance(interaction.user, discord.Member) else None
        is_author = interaction.user.id == int(call["author_id"])
        is_moderator = bool(member and member.guild_permissions.manage_messages)
        if not (is_author or is_moderator):
            await interaction.response.send_message(
                "Закрыть вызов может только автор или модератор.", ephemeral=True
            )
            return

        await interaction.response.defer()
        await self.db.set_status(call_id, "closed")
        call = await self.db.get_call(call_id) or call

        card = await self.render_card(call, closed=True)
        try:
            await interaction.edit_original_response(
                content=f"🔒 **Вызов закрыт** · <@{call['author_id']}>",
                attachments=[discord.File(io.BytesIO(card), filename="call.png")],
                view=CallView(self, call, closed=True),
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except discord.HTTPException:
            log.warning("Не удалось обновить карточку вызова %s", call_id, exc_info=True)

        thread = await self.get_thread(call)
        if thread is not None:
            try:
                await thread.send("🔒 Вызов закрыт. Новые отклики больше не принимаются.")
                await thread.edit(archived=True, locked=True)
            except discord.HTTPException:
                log.warning("Не удалось закрыть ветку %s", thread.id, exc_info=True)

    # --------------------------------------------------------------- helpers
    async def render_card(self, call: dict[str, Any], closed: bool = False) -> bytes:
        avatar: Image.Image | None = None
        try:
            user = self.bot.get_user(int(call["author_id"])) or await self.bot.fetch_user(
                int(call["author_id"])
            )
        except discord.HTTPException:
            user = None
        if user is not None:
            avatar = await load_avatar(user)

        data = CardData(
            name=call["author_display"] or call["author_name"],
            subtitle=f"@{call['author_name']} · заявка на КВ",
            quote=call["quote"],
            chips=[call["time_text"], call["mmr"], call["server"], call["mode"]],
            badge=self.settings.badge,
            brand=self.settings.brand_name,
            brand_note=self.settings.brand_note,
            accent=self.settings.accent,
            closed=closed,
        )
        return await asyncio.to_thread(render_card, data, avatar)

    def build_content(self, call: dict[str, Any]) -> str:
        lines: list[str] = []
        if self.settings.ping_role_id:
            lines.append(f"<@&{self.settings.ping_role_id}>")
        lines.append(f"🎯 <@{call['author_id']}> ищет соперника")
        lines.append(
            f"КВ · {call['time_text']} · {call['mmr']} · {call['server']} · {call['mode']}"
        )
        if call.get("comment"):
            lines.append(f"> {' '.join(str(call['comment']).split())}")
        lines.append("-# Жми «Принять вызов» под карточкой или напиши автору в ЛС")
        return "\n".join(lines)

    def thread_name(self, call: dict[str, Any]) -> str:
        name = f"Вызов · {call['author_display']}"
        return name[:95]

    def thread_intro(self, call: dict[str, Any]) -> discord.Embed:
        embed = discord.Embed(
            title="Ветка вызова",
            description=(
                f"Автор: <@{call['author_id']}>\n"
                "Сюда приходят отклики, автор получает копию в ЛС."
            ),
            color=self.settings.accent_color,
        )
        embed.add_field(
            name="Матч",
            value=f"{call['time_text']} · {call['mmr']} · {call['server']} · {call['mode']}",
            inline=False,
        )
        return embed

    async def get_thread(self, call: dict[str, Any]) -> discord.Thread | None:
        thread_id = call.get("thread_id")
        if not thread_id:
            return None
        thread = self.bot.get_channel(int(thread_id))
        if thread is None:
            try:
                thread = await self.bot.fetch_channel(int(thread_id))
            except discord.HTTPException:
                return None
        if not isinstance(thread, discord.Thread):
            return None
        if thread.archived:
            try:
                await thread.edit(archived=False)
            except discord.HTTPException:
                pass
        return thread

    def allowed_mentions(self) -> discord.AllowedMentions:
        roles = [discord.Object(id=self.settings.ping_role_id)] if self.settings.ping_role_id else []
        return discord.AllowedMentions(everyone=False, users=True, roles=roles)

    async def cog_app_command_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        log.error("Ошибка команды: %s", error, exc_info=error)
        message = "⚠️ Что-то пошло не так. Попробуй ещё раз."
        try:
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)
        except discord.HTTPException:
            pass
