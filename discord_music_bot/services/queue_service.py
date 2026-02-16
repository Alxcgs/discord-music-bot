from typing import List, Dict, Optional, Any
import random
import asyncio
import logging
from discord_music_bot import consts
from discord_music_bot.repository import MusicRepository

logger = logging.getLogger('MusicBot.QueueService')


class QueueService:
    """
    Сервіс черги з in-memory кешем та async-персистентністю в SQLite.
    Дані зберігаються в пам'яті для швидкості, а БД слугує для recovery.
    """

    def __init__(self, repository: MusicRepository):
        self._queues: Dict[int, List[Dict[str, Any]]] = {}
        self._history: Dict[int, List[Dict[str, Any]]] = {}
        self._repo = repository

    # ── Queue Operations ─────────────────────────────────────────

    def get_queue(self, guild_id: int) -> List[Dict[str, Any]]:
        if guild_id not in self._queues:
            self._queues[guild_id] = []
        return self._queues[guild_id]

    def add_track(self, guild_id: int, track: Dict[str, Any]) -> None:
        if guild_id not in self._queues:
            self._queues[guild_id] = []
        self._queues[guild_id].append(track)
        # Фонове збереження в БД
        asyncio.ensure_future(self._persist_queue(guild_id))

    def add_tracks(self, guild_id: int, tracks: List[Dict[str, Any]]) -> None:
        """Додає список треків у чергу (для плейлистів)."""
        if guild_id not in self._queues:
            self._queues[guild_id] = []
        self._queues[guild_id].extend(tracks)
        asyncio.ensure_future(self._persist_queue(guild_id))

    def get_next_track(self, guild_id: int) -> Optional[Dict[str, Any]]:
        """Returns the next track and removes it from the queue."""
        if guild_id in self._queues and self._queues[guild_id]:
            track = self._queues[guild_id].pop(0)
            asyncio.ensure_future(self._persist_queue(guild_id))
            return track
        return None

    def clear(self, guild_id: int) -> None:
        if guild_id in self._queues:
            self._queues[guild_id].clear()
        asyncio.ensure_future(self._repo.clear_queue(guild_id))

    def shuffle(self, guild_id: int) -> None:
        if guild_id in self._queues:
            random.shuffle(self._queues[guild_id])
            asyncio.ensure_future(self._persist_queue(guild_id))

    def push_front(self, guild_id: int, track: Dict[str, Any]) -> None:
        """Adds a track to the front of the queue (priority)."""
        if guild_id not in self._queues:
            self._queues[guild_id] = []
        self._queues[guild_id].insert(0, track)
        asyncio.ensure_future(self._persist_queue(guild_id))

    def peek_next(self, guild_id: int) -> Optional[Dict[str, Any]]:
        """Returns the next track WITHOUT removing it from the queue."""
        if guild_id in self._queues and self._queues[guild_id]:
            return self._queues[guild_id][0]
        return None

    # ── History Management ───────────────────────────────────────

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

    # ── Persistence ──────────────────────────────────────────────

    async def _persist_queue(self, guild_id: int) -> None:
        """Фонове збереження черги в БД."""
        try:
            queue = self.get_queue(guild_id)
            await self._repo.save_queue(guild_id, queue)
        except Exception as e:
            logger.error(f"Помилка збереження черги для {guild_id}: {e}")

    async def load_from_db(self, guild_id: int) -> None:
        """Завантажує чергу та історію з БД в пам'ять (для recovery)."""
        try:
            self._queues[guild_id] = await self._repo.load_queue(guild_id)
            db_history = await self._repo.get_history(guild_id, consts.MAX_HISTORY_SIZE)
            # Нормалізуємо записи — додаємо webpage_url якщо відсутній
            for track in db_history:
                if 'webpage_url' not in track:
                    track['webpage_url'] = track.get('url', '')
            self._history[guild_id] = db_history
            logger.info(
                f"Guild {guild_id}: завантажено {len(self._queues[guild_id])} треків з черги, "
                f"{len(self._history[guild_id])} з історії"
            )
        except Exception as e:
            logger.error(f"Помилка завантаження з БД для {guild_id}: {e}")
            self._queues[guild_id] = []
            self._history[guild_id] = []
