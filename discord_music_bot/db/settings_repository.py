"""
SettingsRepository — збереження налаштувань по guild_id.
"""
import json
import logging
import time
from typing import Any, Optional

import aiosqlite

from discord_music_bot.db.database import get_db_path

logger = logging.getLogger('MusicBot.settings')


class SettingsRepository:
    """Репозиторій налаштувань сервера (гучність, тощо)."""

    def __init__(self, db_path: Optional[str] = None):
        self._db_path = str(db_path) if db_path else str(get_db_path())

    async def get_volume(self, guild_id: int) -> float:
        """Повертає збережену гучність (0.0–1.0), за замовчуванням 0.5."""
        async with aiosqlite.connect(self._db_path) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute(
                "SELECT volume FROM guild_settings WHERE guild_id = ?",
                (guild_id,),
            ) as cur:
                row = await cur.fetchone()
        if row is None:
            return 0.5
        return max(0.0, min(1.0, float(row[0])))

    async def set_volume(self, guild_id: int, volume: float) -> None:
        """Зберігає гучність для сервера."""
        volume = max(0.0, min(1.0, volume))
        now = time.time()
        async with aiosqlite.connect(self._db_path) as conn:
            await conn.execute(
                """
                INSERT INTO guild_settings (guild_id, volume, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(guild_id) DO UPDATE SET volume = ?, updated_at = ?
                """,
                (guild_id, volume, now, volume, now),
            )
            await conn.commit()

    async def get_settings(self, guild_id: int) -> dict:
        """Повертає всі налаштування сервера (словник)."""
        async with aiosqlite.connect(self._db_path) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute(
                "SELECT volume, settings_json FROM guild_settings WHERE guild_id = ?",
                (guild_id,),
            ) as cur:
                row = await cur.fetchone()
        if row is None:
            return {'volume': 0.5}
        out = {'volume': max(0.0, min(1.0, float(row[0])))}
        if row[1]:
            try:
                out.update(json.loads(row[1]))
            except (TypeError, json.JSONDecodeError):
                pass
        return out

    async def set_setting(self, guild_id: int, key: str, value: Any) -> None:
        """Зберігає окреме налаштування (зберігається в settings_json)."""
        settings = await self.get_settings(guild_id)
        settings[key] = value
        volume = settings.pop('volume', 0.5)
        now = time.time()
        async with aiosqlite.connect(self._db_path) as conn:
            await conn.execute(
                """
                INSERT INTO guild_settings (guild_id, volume, settings_json, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(guild_id) DO UPDATE SET volume = ?, settings_json = ?, updated_at = ?
                """,
                (guild_id, volume, json.dumps(settings), now, volume, json.dumps(settings), now),
            )
            await conn.commit()
