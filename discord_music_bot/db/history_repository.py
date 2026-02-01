"""
HistoryRepository — збереження та читання історії відтворених треків.
"""
import logging
import time
from typing import Any, AsyncIterator, List, Optional

import aiosqlite

from discord_music_bot.db.database import get_db_path

logger = logging.getLogger('MusicBot.history')

# Максимум записів історії на сервер
HISTORY_LIMIT = 150


class HistoryRepository:
    """Репозиторій історії відтворень по guild_id."""

    def __init__(self, db_path: Optional[str] = None):
        self._db_path = str(db_path) if db_path else str(get_db_path())

    async def add(
        self,
        guild_id: int,
        requester_id: int,
        title: str,
        *,
        url: Optional[str] = None,
        webpage_url: Optional[str] = None,
        duration: Optional[int] = None,
        thumbnail: Optional[str] = None,
    ) -> None:
        """Додає трек до історії."""
        played_at = time.time()
        async with aiosqlite.connect(self._db_path) as conn:
            conn.row_factory = aiosqlite.Row
            await conn.execute(
                """
                INSERT INTO play_history (guild_id, requester_id, title, url, webpage_url, duration, thumbnail, played_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (guild_id, requester_id, title, url, webpage_url, duration, thumbnail, played_at),
            )
            await conn.commit()
            # Видаляємо зайві записи (залишаємо останні HISTORY_LIMIT)
            await conn.execute(
                """
                DELETE FROM play_history WHERE id IN (
                    SELECT id FROM play_history WHERE guild_id = ?
                    ORDER BY played_at DESC LIMIT -1 OFFSET ?
                )
                """,
                (guild_id, HISTORY_LIMIT),
            )
            await conn.commit()

    async def get_recent(self, guild_id: int, limit: int = HISTORY_LIMIT) -> List[dict]:
        """Повертає останні треки для сервера (нові зверху)."""
        async with aiosqlite.connect(self._db_path) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute(
                """
                SELECT requester_id, title, url, webpage_url, duration, thumbnail
                FROM play_history WHERE guild_id = ?
                ORDER BY played_at DESC LIMIT ?
                """,
                (guild_id, limit),
            ) as cur:
                rows = await cur.fetchall()
        return [
            {
                'requester_id': row[0],
                'title': row[1],
                'url': row[2],
                'webpage_url': row[3],
                'duration': row[4],
                'thumbnail': row[5],
            }
            for row in rows
        ]

    async def clear(self, guild_id: int) -> None:
        """Очищає історію для сервера."""
        async with aiosqlite.connect(self._db_path) as conn:
            await conn.execute("DELETE FROM play_history WHERE guild_id = ?", (guild_id,))
            await conn.commit()
