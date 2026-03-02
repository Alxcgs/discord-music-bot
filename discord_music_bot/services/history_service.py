"""
Сервіс історії прослуховувань (SRP: відокремлений від QueueService).
Керує in-memory історією та async-персистентністю в SQLite.
"""

from typing import List, Dict, Optional, Any
import asyncio
import logging
from discord_music_bot import consts
from discord_music_bot.repository import MusicRepository

logger = logging.getLogger('MusicBot.HistoryService')


class HistoryService:
    """Сервіс історії з in-memory кешем та async-персистентністю в SQLite."""

    def __init__(self, repository: MusicRepository):
        self._history: Dict[int, List[Dict[str, Any]]] = {}
        self._repo = repository

    def add_to_history(self, guild_id: int, track: Dict[str, Any]) -> None:
        if guild_id not in self._history:
            self._history[guild_id] = []
        self._history[guild_id].append(track)
        # Обмежуємо розмір in-memory історії
        if len(self._history[guild_id]) > consts.MAX_HISTORY_SIZE:
            self._history[guild_id].pop(0)
        # Зберігаємо в БД
        asyncio.ensure_future(self._repo.add_history_track(guild_id, track))

    def get_last_track(self, guild_id: int) -> Optional[Dict[str, Any]]:
        """Returns the last played track and removes it from history."""
        if guild_id in self._history and self._history[guild_id]:
            track = self._history[guild_id].pop()
            # Видаляємо й з БД
            asyncio.ensure_future(self._repo.pop_last_history_track(guild_id))
            return track
        return None

    def clear_history(self, guild_id: int) -> None:
        """Очищає всю історію прослуховувань (in-memory + БД)."""
        if guild_id in self._history:
            self._history[guild_id].clear()
        asyncio.ensure_future(self._repo.clear_history(guild_id))

    async def load_from_db(self, guild_id: int) -> None:
        """Завантажує історію з БД в пам'ять (для recovery)."""
        try:
            db_history = await self._repo.get_history(guild_id, consts.MAX_HISTORY_SIZE)
            # Нормалізуємо записи — додаємо webpage_url якщо відсутній
            for track in db_history:
                if 'webpage_url' not in track:
                    track['webpage_url'] = track.get('url', '')
            self._history[guild_id] = db_history
            logger.info(
                f"Guild {guild_id}: завантажено {len(self._history[guild_id])} з історії"
            )
        except Exception as e:
            logger.error(f"Помилка завантаження історії з БД для {guild_id}: {e}")
            self._history[guild_id] = []
