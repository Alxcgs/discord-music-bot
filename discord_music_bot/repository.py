"""
Repository pattern для абстрагування роботи з базою даних.
Відділяє бізнес-логіку від деталей зберігання даних.
"""

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
        Використовує транзакцію та executemany для ефективності.
        """
        conn = await get_connection()
        try:
            await conn.execute(
                "DELETE FROM queue_tracks WHERE guild_id = ?", (guild_id,)
            )
            if tracks:
                await conn.executemany(
                    """
                    INSERT INTO queue_tracks 
                        (guild_id, position, url, title, duration, thumbnail)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            guild_id,
                            pos,
                            track.get("url") or track.get("webpage_url", ""),
                            track.get("title", "Unknown"),
                            track.get("duration"),
                            track.get("thumbnail"),
                        )
                        for pos, track in enumerate(tracks)
                    ],
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

    async def clear_history(self, guild_id: int) -> None:
        """Видаляє всю історію прослуховувань для сервера."""
        conn = await get_connection()
        try:
            await conn.execute(
                "DELETE FROM history_tracks WHERE guild_id = ?", (guild_id,)
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

    # ── Automix (Diploma Extensions) ─────────────────────────────

    async def get_automix_settings(self, guild_id: int) -> Optional[Dict[str, Any]]:
        """Returns None if no row; else {enabled: bool, strategy: str}."""
        conn = await get_connection()
        try:
            cursor = await conn.execute(
                "SELECT enabled, strategy FROM automix_settings WHERE guild_id = ?",
                (guild_id,),
            )
            row = await cursor.fetchone()
            if not row:
                return None
            d = dict(row)
            strat = d.get("strategy")
            return {
                "enabled": bool(d["enabled"]),
                "strategy": strat if strat else "ab_split",
            }
        finally:
            await conn.close()

    async def get_automix_enabled(self, guild_id: int) -> Optional[bool]:
        """Returns None if no explicit setting exists yet."""
        s = await self.get_automix_settings(guild_id)
        if s is None:
            return None
        return s["enabled"]

    async def set_automix_enabled(self, guild_id: int, enabled: bool) -> None:
        conn = await get_connection()
        try:
            await conn.execute(
                """
                INSERT INTO automix_settings (guild_id, enabled, strategy, updated_at)
                VALUES (?, ?, 'ab_split', CURRENT_TIMESTAMP)
                ON CONFLICT(guild_id) DO UPDATE SET
                    enabled = excluded.enabled,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (guild_id, int(enabled)),
            )
            await conn.commit()
        finally:
            await conn.close()

    async def set_automix_strategy(self, guild_id: int, strategy: str) -> None:
        conn = await get_connection()
        try:
            cur = await conn.execute(
                """
                UPDATE automix_settings
                SET strategy = ?, updated_at = CURRENT_TIMESTAMP
                WHERE guild_id = ?
                """,
                (strategy, guild_id),
            )
            if cur.rowcount == 0:
                await conn.execute(
                    """
                    INSERT INTO automix_settings (guild_id, enabled, strategy, updated_at)
                    VALUES (?, 0, ?, CURRENT_TIMESTAMP)
                    """,
                    (guild_id, strategy),
                )
            await conn.commit()
        finally:
            await conn.close()

    async def increment_automix_skip(self, guild_id: int, track_url: str) -> None:
        conn = await get_connection()
        try:
            await conn.execute(
                """
                INSERT INTO automix_penalties (guild_id, track_url, skip_count, last_skipped_at)
                VALUES (?, ?, 1, CURRENT_TIMESTAMP)
                ON CONFLICT(guild_id, track_url) DO UPDATE SET
                    skip_count = skip_count + 1,
                    last_skipped_at = CURRENT_TIMESTAMP
                """,
                (guild_id, track_url),
            )
            await conn.commit()
        finally:
            await conn.close()

    async def get_automix_skip_penalties(self, guild_id: int, limit: int = 500) -> Dict[str, int]:
        conn = await get_connection()
        try:
            cursor = await conn.execute(
                """
                SELECT track_url, skip_count
                FROM automix_penalties
                WHERE guild_id = ?
                ORDER BY skip_count DESC
                LIMIT ?
                """,
                (guild_id, limit),
            )
            rows = await cursor.fetchall()
            return {r["track_url"]: int(r["skip_count"] or 0) for r in rows}
        finally:
            await conn.close()

    async def add_automix_feedback_event(
        self,
        guild_id: int,
        action: str,
        track_url: Optional[str] = None,
        strategy: Optional[str] = None,
    ) -> None:
        conn = await get_connection()
        try:
            await conn.execute(
                """
                INSERT INTO automix_feedback_events (guild_id, track_url, action, strategy)
                VALUES (?, ?, ?, ?)
                """,
                (guild_id, track_url, action, strategy),
            )
            await conn.commit()
        finally:
            await conn.close()

    async def get_automix_feedback_counts(self, guild_id: int, days: int = 30) -> Dict[str, int]:
        """Returns counts by action in last N days."""
        conn = await get_connection()
        try:
            cursor = await conn.execute(
                """
                SELECT action, COUNT(*) as cnt
                FROM automix_feedback_events
                WHERE guild_id = ?
                  AND created_at >= datetime('now', ? || ' days')
                GROUP BY action
                """,
                (guild_id, -days),
            )
            rows = await cursor.fetchall()
            out: Dict[str, int] = {}
            for r in rows:
                out[str(r["action"])] = int(r["cnt"] or 0)
            return out
        finally:
            await conn.close()

    async def get_automix_ab_comparison(self, guild_id: int, days: int = 30) -> List[Dict[str, Any]]:
        """Порівняння A/B: recommended/skips по strategy (для диплому)."""
        conn = await get_connection()
        try:
            cursor = await conn.execute(
                """
                SELECT COALESCE(strategy, '') AS strat, action, COUNT(*) AS cnt
                FROM automix_feedback_events
                WHERE guild_id = ?
                  AND created_at >= datetime('now', ? || ' days')
                  AND action IN ('recommended', 'skipped')
                  AND strategy IS NOT NULL
                  AND strategy != ''
                GROUP BY strat, action
                """,
                (guild_id, -days),
            )
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]
        finally:
            await conn.close()

    async def get_automix_diversity_stats(self, guild_id: int, days: int = 30) -> Dict[str, int]:
        """Унікальність рекомендацій: distinct URLs / total recommended."""
        conn = await get_connection()
        try:
            cursor = await conn.execute(
                """
                SELECT
                    COUNT(*) AS rec_total,
                    COUNT(DISTINCT track_url) AS rec_distinct
                FROM automix_feedback_events
                WHERE guild_id = ?
                  AND action = 'recommended'
                  AND created_at >= datetime('now', ? || ' days')
                """,
                (guild_id, -days),
            )
            row = await cursor.fetchone()
            if not row:
                return {"rec_total": 0, "rec_distinct": 0}
            return {
                "rec_total": int(row["rec_total"] or 0),
                "rec_distinct": int(row["rec_distinct"] or 0),
            }
        finally:
            await conn.close()
