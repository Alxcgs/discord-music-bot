"""
QueueRepository — збереження стану черги та плеєра.
"""
import json
import logging
import time
from typing import Any, List, Optional

import aiosqlite

from discord_music_bot.db.database import get_db_path

logger = logging.getLogger('MusicBot.queue_repo')


class QueueRepository:
    """Репозиторій для збереження стану черги."""

    def __init__(self, db_path: Optional[str] = None):
        self._db_path = str(db_path) if db_path else str(get_db_path())

    async def save_state(
        self,
        guild_id: int,
        voice_channel_id: Optional[int],
        text_channel_id: Optional[int],
        current_track: Optional[dict] = None,
        is_paused: bool = False
    ) -> None:
        """Зберігає загальний стан плеєра."""
        now = time.time()
        track_json = None
        if current_track:
            # Зберігаємо лише необхідні поля для відновлення
            track_json = json.dumps({
                'title': current_track.get('title'),
                'url': current_track.get('url'),
                'webpage_url': current_track.get('webpage_url'),
                'duration': current_track.get('duration'),
                'thumbnail': current_track.get('thumbnail'),
                # requester не зберігаємо, бо він не важливий для авто-відновлення, або можна ID
                'requester_id': getattr(current_track.get('requester'), 'id', None)
            })

        async with aiosqlite.connect(self._db_path) as conn:
            await conn.execute(
                """
                INSERT INTO queue_state (guild_id, voice_channel_id, text_channel_id, current_track_json, is_paused, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(guild_id) DO UPDATE SET 
                    voice_channel_id = ?, 
                    text_channel_id = ?, 
                    current_track_json = ?, 
                    is_paused = ?, 
                    updated_at = ?
                """,
                (
                    guild_id, voice_channel_id, text_channel_id, track_json, int(is_paused), now,
                    voice_channel_id, text_channel_id, track_json, int(is_paused), now
                )
            )
            await conn.commit()

    async def get_state(self, guild_id: int) -> Optional[dict]:
        """Повертає стан плеєра."""
        async with aiosqlite.connect(self._db_path) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute(
                "SELECT voice_channel_id, text_channel_id, current_track_json, is_paused FROM queue_state WHERE guild_id = ?",
                (guild_id,)
            ) as cur:
                row = await cur.fetchone()
        
        if not row:
            return None
            
        current_track = None
        if row['current_track_json']:
            try:
                current_track = json.loads(row['current_track_json'])
            except:
                pass

        return {
            'voice_channel_id': row['voice_channel_id'],
            'text_channel_id': row['text_channel_id'],
            'current_track': current_track,
            'is_paused': bool(row['is_paused'])
        }

    async def save_queue(self, guild_id: int, items: List[dict]) -> None:
        """Повністю перезаписує чергу для сервера."""
        # Для SQLite це нормально, якщо черга не величезна (<1000 items)
        async with aiosqlite.connect(self._db_path) as conn:
            # Спочатку видаляємо старі елементи
            await conn.execute("DELETE FROM queue_items WHERE guild_id = ?", (guild_id,))
            
            # Додаємо нові
            if items:
                params = []
                for i, item in enumerate(items):
                    # Мінімізуємо збережені дані
                    save_item = {
                        'title': item.get('title'),
                        'url': item.get('url'),
                        'webpage_url': item.get('webpage_url'),
                        'duration': item.get('duration'),
                        'thumbnail': item.get('thumbnail'),
                        'requester_id': getattr(item.get('requester'), 'id', None)
                    }
                    params.append((guild_id, i, json.dumps(save_item)))
                
                await conn.executemany(
                    "INSERT INTO queue_items (guild_id, position, track_json) VALUES (?, ?, ?)",
                    params
                )
            await conn.commit()

    async def get_queue(self, guild_id: int) -> List[dict]:
        """Отримує список треків у черзі."""
        async with aiosqlite.connect(self._db_path) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute(
                "SELECT track_json FROM queue_items WHERE guild_id = ? ORDER BY position ASC",
                (guild_id,)
            ) as cur:
                rows = await cur.fetchall()
        
        items = []
        for row in rows:
            try:
                item = json.loads(row['track_json'])
                items.append(item)
            except:
                continue
        return items

    async def clear_all(self, guild_id: int) -> None:
        """Повністю видаляє інформацію про стан сервера (при leave)."""
        async with aiosqlite.connect(self._db_path) as conn:
            await conn.execute("DELETE FROM queue_items WHERE guild_id = ?", (guild_id,))
            await conn.execute("DELETE FROM queue_state WHERE guild_id = ?", (guild_id,))
            await conn.commit()
