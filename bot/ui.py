"""Модалки, кнопки и предпросмотр вызова."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any

import discord

if TYPE_CHECKING:
    from .calls import Calls


class PublishError(Exception):
    """Понятная пользователю ошибка публикации."""


SERVERS = ("Europe", "Russia", "SEA", "US East", "US West", "Dubai", "Другой")
MODES = ("Captains Mode", "All Pick", "Turbo", "1x1 Mid", "5x5 Custom")

MAX_OPEN_CALLS = 3


@dataclass
class Draft:
    quote: str
    mmr: str
    time_text: str
    comment: str = ""
    server: str = "Europe"
    mode: str = "Captains Mode"


def draft_embed(draft: Draft, cog: Calls, user: discord.abc.User) -> discord.Embed:
    embed = discord.Embed(
        title="Предпросмотр вызова",
        description=f"**«{draft.quote}»**",
        color=cog.settings.accent_color,
    )
    embed.add_field(name="MMR / уровень", value=draft.mmr, inline=True)
    embed.add_field(name="Время", value=draft.time_text, inline=True)
    embed.add_field(name="Сервер", value=draft.server, inline=True)
    embed.add_field(name="Режим", value=draft.mode, inline=True)
    if draft.comment:
        embed.add_field(name="Кого ищете / комментарий", value=draft.comment[:1024], inline=False)
    embed.set_thumbnail(url=user.display_avatar.url)
    embed.set_footer(text="Проверь данные и нажми «Опубликовать»")
    return embed


class NewCallModal(discord.ui.Modal, title="Новый вызов на КВ"):
    quote = discord.ui.TextInput(
        label="Заголовок вызова",
        placeholder="20:00 без смурфов",
        max_length=80,
        required=True,
    )
    mmr = discord.ui.TextInput(
        label="MMR / уровень",
        placeholder="3 250 MMR",
        max_length=40,
        required=True,
    )
    time_text = discord.ui.TextInput(
        label="Время матча",
        placeholder="Сегодня 20:00 МСК",
        max_length=60,
        required=True,
    )
    comment = discord.ui.TextInput(
        label="Кого ищете / комментарий",
        placeholder="Нужна команда 5x5, свой войс, можем подождать",
        style=discord.TextStyle.paragraph,
        max_length=300,
        required=False,
    )

    def __init__(self, cog: Calls) -> None:
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction) -> None:
        draft = Draft(
            quote=str(self.quote.value).strip(),
            mmr=str(self.mmr.value).strip(),
            time_text=str(self.time_text.value).strip(),
            comment=str(self.comment.value or "").strip(),
        )
        view = PreviewView(self.cog, draft)
        await interaction.response.send_message(
            embed=draft_embed(draft, self.cog, interaction.user),
            view=view,
            ephemeral=True,
        )


class PreviewView(discord.ui.View):
    def __init__(self, cog: Calls, draft: Draft) -> None:
        super().__init__(timeout=600)
        self.cog = cog
        self.draft = draft

        self.server_select = discord.ui.Select(
            placeholder="Сервер",
            options=[
                discord.SelectOption(label=value, value=value, default=value == draft.server)
                for value in SERVERS
            ],
            row=0,
        )
        self.server_select.callback = self.on_server  # type: ignore[method-assign]
        self.add_item(self.server_select)

        self.mode_select = discord.ui.Select(
            placeholder="Режим",
            options=[
                discord.SelectOption(label=value, value=value, default=value == draft.mode)
                for value in MODES
            ],
            row=1,
        )
        self.mode_select.callback = self.on_mode  # type: ignore[method-assign]
        self.add_item(self.mode_select)

        publish = discord.ui.Button(
            label="Опубликовать",
            emoji="🚀",
            style=discord.ButtonStyle.success,
            row=2,
        )
        publish.callback = self.on_publish  # type: ignore[method-assign]
        self.add_item(publish)

        cancel = discord.ui.Button(
            label="Отмена",
            style=discord.ButtonStyle.secondary,
            row=2,
        )
        cancel.callback = self.on_cancel  # type: ignore[method-assign]
        self.add_item(cancel)

    def _refresh_selects(self) -> None:
        self.server_select.options = [
            discord.SelectOption(label=value, value=value, default=value == self.draft.server)
            for value in SERVERS
        ]
        self.mode_select.options = [
            discord.SelectOption(label=value, value=value, default=value == self.draft.mode)
            for value in MODES
        ]

    async def on_server(self, interaction: discord.Interaction) -> None:
        self.draft = replace(self.draft, server=str(self.server_select.values[0]))
        self._refresh_selects()
        await interaction.response.edit_message(
            embed=draft_embed(self.draft, self.cog, interaction.user), view=self
        )

    async def on_mode(self, interaction: discord.Interaction) -> None:
        self.draft = replace(self.draft, mode=str(self.mode_select.values[0]))
        self._refresh_selects()
        await interaction.response.edit_message(
            embed=draft_embed(self.draft, self.cog, interaction.user), view=self
        )

    async def on_publish(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        try:
            message = await self.cog.publish(interaction, self.draft)
        except PublishError as error:
            await interaction.edit_original_response(
                content=f"⚠️ {error}",
                embed=draft_embed(self.draft, self.cog, interaction.user),
                view=self,
            )
            return
        except Exception:
            self.cog.log.exception("Не удалось опубликовать вызов")
            await interaction.edit_original_response(
                content="⚠️ Не удалось опубликовать вызов. Попробуй ещё раз чуть позже.",
                embed=draft_embed(self.draft, self.cog, interaction.user),
                view=self,
            )
            return

        self.stop()
        success = discord.Embed(
            title="✅ Вызов опубликован",
            description=f"[Перейти к карточке]({message.jump_url})",
            color=0x3BA55D,
        )
        await interaction.edit_original_response(content=None, embed=success, view=None)

    async def on_cancel(self, interaction: discord.Interaction) -> None:
        self.stop()
        await interaction.response.edit_message(content="Создание вызова отменено.", embed=None, view=None)


class AcceptModal(discord.ui.Modal, title="Принять вызов"):
    team_level = discord.ui.TextInput(
        label="Уровень вашей команды (необязательно)",
        placeholder="Например, 5000",
        max_length=40,
        required=False,
    )
    note = discord.ui.TextInput(
        label="Запись (необязательно)",
        placeholder="можем в 21:00, свой войс",
        style=discord.TextStyle.paragraph,
        max_length=300,
        required=False,
    )

    def __init__(self, cog: Calls, call_id: int) -> None:
        super().__init__()
        self.cog = cog
        self.call_id = call_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            await self.cog.accept_call(
                interaction,
                self.call_id,
                str(self.team_level.value or "").strip(),
                str(self.note.value or "").strip(),
            )
        except Exception:
            self.cog.log.exception("Не удалось отправить отклик на вызов %s", self.call_id)
            message = "⚠️ Не удалось отправить отклик. Попробуй ещё раз."
            if interaction.response.is_done():
                await interaction.edit_original_response(content=message)
            else:
                await interaction.response.send_message(message, ephemeral=True)


class CallView(discord.ui.View):
    """Кнопки под карточкой. Персистентная: восстанавливается после рестарта."""

    def __init__(self, cog: Calls, call: dict[str, Any], closed: bool = False) -> None:
        super().__init__(timeout=None)
        self.cog = cog
        self.call = dict(call)
        call_id = int(self.call["id"])

        accept = discord.ui.Button(
            label="Принять вызов",
            emoji="🤝",
            style=discord.ButtonStyle.success,
            custom_id=f"call:accept:{call_id}",
            disabled=closed,
            row=0,
        )
        accept.callback = self.on_accept  # type: ignore[method-assign]
        self.add_item(accept)

        profile = discord.ui.Button(
            label="Профиль автора",
            emoji="👤",
            style=discord.ButtonStyle.link,
            url=f"https://discord.com/users/{int(self.call['author_id'])}",
            row=0,
        )
        self.add_item(profile)

        close = discord.ui.Button(
            label="Закрыть вызов",
            emoji="🔒",
            style=discord.ButtonStyle.secondary,
            custom_id=f"call:close:{call_id}",
            disabled=closed,
            row=0,
        )
        close.callback = self.on_close  # type: ignore[method-assign]
        self.add_item(close)

    async def on_accept(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(AcceptModal(self.cog, int(self.call["id"])))

    async def on_close(self, interaction: discord.Interaction) -> None:
        await self.cog.close_call(interaction, int(self.call["id"]))


class PanelView(discord.ui.View):
    def __init__(self, cog: Calls) -> None:
        super().__init__(timeout=None)
        self.cog = cog
        button = discord.ui.Button(
            label="Создать вызов",
            emoji="🎫",
            style=discord.ButtonStyle.primary,
            custom_id="panel:create",
        )
        button.callback = self.on_create  # type: ignore[method-assign]
        self.add_item(button)

    async def on_create(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(NewCallModal(self.cog))
