"""
Repository pattern для абстрагування роботи з базою даних.
Відділяє бізнес-логіку від деталей зберігання даних.
"""

import aiosqlite
import logging
from typing import List, Dict, Optional, Any
from discord_music_bot.database import get_connection

logger = logging.getLogger('MusicBot.Repository')


class MusicRepository:
    """Асинхронний репозиторій для роботи з музичними даними."""

    # ── Guild State ──────────────────────────────────────────────

    async def save_guild_state(
        self,
        guild_id: int,
        voice_channel_id: Optional[int] = None,
        text_channel_id: Optional[int] = None,
        track_url: Optional[str] = None,
        track_title: Optional[str] = None,
        track_duration: Optional[int] = None,
        track_thumbnail: Optional[str] = None,
        is_paused: bool = False,
    ) -> None:
        """Зберігає або оновлює стан бота для конкретного сервера."""
        conn = await get_connection()
        try:
            await conn.execute(
                """
                INSERT INTO guild_state 
                    (guild_id, voice_channel_id, text_channel_id,
                     current_track_url, current_track_title, current_track_duration,
                     current_track_thumbnail, is_paused, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(guild_id) DO UPDATE SET
                    voice_channel_id = excluded.voice_channel_id,
                    text_channel_id = excluded.text_channel_id,
                    current_track_url = excluded.current_track_url,
                    current_track_title = excluded.current_track_title,
                    current_track_duration = excluded.current_track_duration,
                    current_track_thumbnail = excluded.current_track_thumbnail,
                    is_paused = excluded.is_paused,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (guild_id, voice_channel_id, text_channel_id,
                 track_url, track_title, track_duration,
                 track_thumbnail, int(is_paused)),
            )
            await conn.commit()
        finally:
            await conn.close()

    async def load_guild_state(self, guild_id: int) -> Optional[Dict[str, Any]]:
        """Завантажує збережений стан для сервера."""
        conn = await get_connection()
        try:
            cursor = await conn.execute(
                "SELECT * FROM guild_state WHERE guild_id = ?", (guild_id,)
            )
            row = await cursor.fetchone()
            if row is None:
                return None
            return dict(row)
        finally:
            await conn.close()

    async def get_all_active_guilds(self) -> List[Dict[str, Any]]:
        """Повертає всі guild з активним voice_channel (для auto-resume)."""
        conn = await get_connection()
        try:
            cursor = await conn.execute(
                """
                SELECT * FROM guild_state 
                WHERE voice_channel_id IS NOT NULL 
                  AND current_track_url IS NOT NULL
                """
            )
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]
        finally:
            await conn.close()

    async def clear_guild_state(self, guild_id: int) -> None:
        """Очищає стан сервера (бот відключився)."""
        conn = await get_connection()
        try:
            await conn.execute(
                """
                UPDATE guild_state SET
                    voice_channel_id = NULL,
                    text_channel_id = NULL,
                    current_track_url = NULL,
                    current_track_title = NULL,
                    current_track_duration = NULL,
                    current_track_thumbnail = NULL,
                    is_paused = 0,
                    updated_at = CURRENT_TIMESTAMP
                WHERE guild_id = ?
                """,
                (guild_id,),
            )
            await conn.commit()
        finally:
            await conn.close()

    # ── Queue ────────────────────────────────────────────────────

    async def save_queue(self, guild_id: int, tracks: List[Dict[str, Any]]) -> None:
        """
        Атомарно зберігає чергу — видаляє стару і записує нову.
        Використовує транзакцію для консистентності.
        """
        conn = await get_connection()
        try:
            await conn.execute(
                "DELETE FROM queue_tracks WHERE guild_id = ?", (guild_id,)
            )
            for pos, track in enumerate(tracks):
                await conn.execute(
                    """
                    INSERT INTO queue_tracks 
                        (guild_id, position, url, title, duration, thumbnail)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        guild_id,
                        pos,
                        track.get("url") or track.get("webpage_url", ""),
                        track.get("title", "Unknown"),
                        track.get("duration"),
                        track.get("thumbnail"),
                    ),
                )
            await conn.commit()
        finally:
            await conn.close()

    async def load_queue(self, guild_id: int) -> List[Dict[str, Any]]:
        """Завантажує чергу для сервера з БД."""
        conn = await get_connection()
        try:
            cursor = await conn.execute(
                """
                SELECT url, title, duration, thumbnail 
                FROM queue_tracks 
                WHERE guild_id = ? 
                ORDER BY position ASC
                """,
                (guild_id,),
            )
            rows = await cursor.fetchall()
            return [
                {
                    "url": r["url"],
                    "webpage_url": r["url"],
                    "title": r["title"],
                    "duration": r["duration"],
                    "thumbnail": r["thumbnail"],
                }
                for r in rows
            ]
        finally:
            await conn.close()

    async def clear_queue(self, guild_id: int) -> None:
        """Видаляє чергу для сервера."""
        conn = await get_connection()
        try:
            await conn.execute(
                "DELETE FROM queue_tracks WHERE guild_id = ?", (guild_id,)
            )
            await conn.commit()
        finally:
            await conn.close()

    # ── History ──────────────────────────────────────────────────

    async def add_history_track(self, guild_id: int, track: Dict[str, Any]) -> None:
        """Додає трек в історію прослуховувань."""
        conn = await get_connection()
        try:
            await conn.execute(
                """
                INSERT INTO history_tracks 
                    (guild_id, url, title, duration, thumbnail)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    guild_id,
                    track.get("url") or track.get("webpage_url", ""),
                    track.get("title", "Unknown"),
                    track.get("duration"),
                    track.get("thumbnail"),
                ),
            )
            # Тримаємо максимум 200 записів на guild, видаляємо найстаріші
            await conn.execute(
                """
                DELETE FROM history_tracks 
                WHERE guild_id = ? AND id NOT IN (
                    SELECT id FROM history_tracks 
                    WHERE guild_id = ? 
                    ORDER BY played_at DESC 
                    LIMIT 200
                )
                """,
                (guild_id, guild_id),
            )
            await conn.commit()
        finally:
            await conn.close()

    async def get_history(
        self, guild_id: int, limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Повертає історію прослуховувань (від найновіших)."""
        conn = await get_connection()
        try:
            cursor = await conn.execute(
                """
                SELECT url, title, duration, thumbnail, played_at
                FROM history_tracks
                WHERE guild_id = ?
                ORDER BY played_at DESC
                LIMIT ?
                """,
                (guild_id, limit),
            )
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]
        finally:
            await conn.close()

    async def pop_last_history_track(self, guild_id: int) -> Optional[Dict[str, Any]]:
        """Повертає та видаляє останній трек з історії (для кнопки Previous)."""
        conn = await get_connection()
        try:
            cursor = await conn.execute(
                """
                SELECT id, url, title, duration, thumbnail
                FROM history_tracks
                WHERE guild_id = ?
                ORDER BY played_at DESC
                LIMIT 1
                """,
                (guild_id,),
            )
            row = await cursor.fetchone()
            if row is None:
                return None
            track = {
                "url": row["url"],
                "webpage_url": row["url"],
                "title": row["title"],
                "duration": row["duration"],
                "thumbnail": row["thumbnail"],
            }
            await conn.execute(
                "DELETE FROM history_tracks WHERE id = ?", (row["id"],)
            )
            await conn.commit()
            return track
        finally:
            await conn.close()

    # ── Analytics (Етап 5) ───────────────────────────────────────

    async def get_top_tracks(
        self, guild_id: int, limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Найчастіше прослуховувані треки."""
        conn = await get_connection()
        try:
            cursor = await conn.execute(
                """
                SELECT url, title, duration, thumbnail, 
                       COUNT(*) as play_count
                FROM history_tracks
                WHERE guild_id = ?
                GROUP BY url
                ORDER BY play_count DESC
                LIMIT ?
                """,
                (guild_id, limit),
            )
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]
        finally:
            await conn.close()

    async def get_total_listening_time(self, guild_id: int) -> int:
        """Загальний час прослуховування (секунди)."""
        conn = await get_connection()
        try:
            cursor = await conn.execute(
                """
                SELECT COALESCE(SUM(duration), 0) as total_seconds
                FROM history_tracks
                WHERE guild_id = ? AND duration IS NOT NULL
                """,
                (guild_id,),
            )
            row = await cursor.fetchone()
            return row["total_seconds"] if row else 0
        finally:
            await conn.close()

    async def get_listening_stats(
        self, guild_id: int, days: int = 30
    ) -> Dict[str, Any]:
        """Статистика прослуховування за N днів."""
        conn = await get_connection()
        try:
            cursor = await conn.execute(
                """
                SELECT 
                    COUNT(*) as total_tracks,
                    COUNT(DISTINCT url) as unique_tracks,
                    COALESCE(SUM(duration), 0) as total_seconds
                FROM history_tracks
                WHERE guild_id = ?
                  AND played_at >= datetime('now', ? || ' days')
                """,
                (guild_id, -days),
            )
            row = await cursor.fetchone()
            return dict(row) if row else {
                "total_tracks": 0,
                "unique_tracks": 0,
                "total_seconds": 0,
            }
        finally:
            await conn.close()

    async def search_history(
        self, guild_id: int, query: str, limit: int = 20
    ) -> List[Dict[str, Any]]:
        """Пошук в історії прослуховувань по назві."""
        conn = await get_connection()
        try:
            cursor = await conn.execute(
                """
                SELECT url, title, duration, thumbnail, played_at
                FROM history_tracks
                WHERE guild_id = ? AND title LIKE ?
                ORDER BY played_at DESC
                LIMIT ?
                """,
                (guild_id, f"%{query}%", limit),
            )
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]
        finally:
            await conn.close()
