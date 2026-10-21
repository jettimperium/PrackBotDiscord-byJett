"""Настройки бота из .env."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def _optional_int(name: str) -> int | None:
    raw = os.getenv(name, "").strip().strip('"').strip("'")
    return int(raw) if raw.isdigit() else None


@dataclass(frozen=True)
class Settings:
    token: str
    calls_channel_id: int | None = None
    guild_id: int | None = None
    ping_role_id: int | None = None
    accent: str = "#ff4d6d"
    badge: str = "КВ · DOTA 2"
    brand_name: str = "P2P"
    brand_note: str = "быстрое КВ"
    db_path: Path = ROOT / "data" / "calls.db"

    @property
    def accent_color(self) -> int:
        raw = self.accent.strip().lstrip("#")
        if len(raw) == 3:
            raw = "".join(ch * 2 for ch in raw)
        try:
            return int(raw, 16)
        except ValueError:
            return 0xFF4D6D


def load_settings() -> Settings:
    token = os.getenv("DISCORD_TOKEN", "").strip().strip('"').strip("'")
    if not token:
        raise SystemExit(
            "Не задан DISCORD_TOKEN.\n"
            "Скопируй .env.example в .env и вставь токен бота из Discord Developer Portal."
        )

    return Settings(
        token=token,
        calls_channel_id=_optional_int("CALLS_CHANNEL_ID"),
        guild_id=_optional_int("GUILD_ID"),
        ping_role_id=_optional_int("PING_ROLE_ID"),
        accent=os.getenv("CARD_ACCENT", "#ff4d6d").strip() or "#ff4d6d",
        badge=os.getenv("CARD_BADGE", "КВ · DOTA 2").strip() or "КВ · DOTA 2",
        brand_name=os.getenv("BRAND_NAME", "P2P").strip() or "P2P",
        brand_note=os.getenv("BRAND_NOTE", "быстрое КВ").strip() or "быстрое КВ",
    )
