"""
Модуль ініціалізації бази даних SQLite.
Створює таблиці для зберігання стану черг, історії та guild-state.
"""

import aiosqlite
import os
import logging

logger = logging.getLogger('MusicBot.Database')

# Шлях до файлу БД — конфігурується через змінну середовища або за замовчуванням data/
DB_DIR = os.environ.get('DB_DATA_DIR', os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data'))
DB_PATH = os.path.join(DB_DIR, 'music_bot.db')

# SQL для створення таблиць
_CREATE_TABLES_SQL = """
-- Стан бота для кожного сервера (guild)
CREATE TABLE IF NOT EXISTS guild_state (
    guild_id        INTEGER PRIMARY KEY,
    voice_channel_id INTEGER,
    text_channel_id  INTEGER,
    current_track_url   TEXT,
    current_track_title TEXT,
    current_track_duration INTEGER,
    current_track_thumbnail TEXT,
    is_paused       INTEGER DEFAULT 0,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Черга треків
CREATE TABLE IF NOT EXISTS queue_tracks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id    INTEGER NOT NULL,
    position    INTEGER NOT NULL,
    url         TEXT NOT NULL,
    title       TEXT,
    duration    INTEGER,
    thumbnail   TEXT,
    added_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (guild_id) REFERENCES guild_state(guild_id)
);

-- Індекс для швидкого отримання черги по guild_id
CREATE INDEX IF NOT EXISTS idx_queue_guild_position ON queue_tracks(guild_id, position);

-- Історія прослуховувань
CREATE TABLE IF NOT EXISTS history_tracks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id    INTEGER NOT NULL,
    url         TEXT NOT NULL,
    title       TEXT,
    duration    INTEGER,
    thumbnail   TEXT,
    played_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (guild_id) REFERENCES guild_state(guild_id)
);

-- Індекс для швидкого отримання історії по guild_id
CREATE INDEX IF NOT EXISTS idx_history_guild_played ON history_tracks(guild_id, played_at DESC);

-- Automix settings (per guild)
CREATE TABLE IF NOT EXISTS automix_settings (
    guild_id    INTEGER PRIMARY KEY,
    enabled     INTEGER NOT NULL DEFAULT 0,
    strategy    TEXT DEFAULT 'ab_split',
    updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (guild_id) REFERENCES guild_state(guild_id)
);

-- Automix penalties (simple feedback: skip counts for recommended tracks)
CREATE TABLE IF NOT EXISTS automix_penalties (
    guild_id        INTEGER NOT NULL,
    track_url       TEXT NOT NULL,
    skip_count      INTEGER NOT NULL DEFAULT 0,
    last_skipped_at TIMESTAMP,
    PRIMARY KEY (guild_id, track_url),
    FOREIGN KEY (guild_id) REFERENCES guild_state(guild_id)
);

CREATE INDEX IF NOT EXISTS idx_automix_penalties_guild ON automix_penalties(guild_id, skip_count DESC);

-- Automix feedback events (for analytics / дипломні метрики)
CREATE TABLE IF NOT EXISTS automix_feedback_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id    INTEGER NOT NULL,
    track_url   TEXT,
    action      TEXT NOT NULL, -- recommended, skipped, queue_empty_checked, no_recommendation
    strategy    TEXT,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (guild_id) REFERENCES guild_state(guild_id)
);

CREATE INDEX IF NOT EXISTS idx_automix_feedback_guild_time ON automix_feedback_events(guild_id, created_at DESC);
"""


async def _migrate_automix_schema(conn: aiosqlite.Connection) -> None:
    """Додає колонки strategy для існуючих БД (CREATE IF NOT EXISTS їх не оновлює)."""
    async def column_names(table: str) -> set:
        cur = await conn.execute(f"PRAGMA table_info({table})")
        rows = await cur.fetchall()
        return {r[1] for r in rows}

    try:
        names = await column_names("automix_settings")
        if "strategy" not in names:
            await conn.execute(
                "ALTER TABLE automix_settings ADD COLUMN strategy TEXT DEFAULT 'ab_split'"
            )
    except Exception as e:
        logger.warning(f"Міграція automix_settings.strategy: {e}")

    try:
        names = await column_names("automix_feedback_events")
        if "strategy" not in names:
            await conn.execute(
                "ALTER TABLE automix_feedback_events ADD COLUMN strategy TEXT"
            )
    except Exception as e:
        logger.warning(f"Міграція automix_feedback_events.strategy: {e}")

    await conn.commit()


async def get_connection() -> aiosqlite.Connection:
    """Створює та повертає з'єднання з БД."""
    os.makedirs(DB_DIR, exist_ok=True)
    conn = await aiosqlite.connect(DB_PATH)
    conn.row_factory = aiosqlite.Row
    # Увімкнути WAL mode для кращої конкурентності
    await conn.execute("PRAGMA journal_mode=WAL")
    # Увімкнути foreign keys
    await conn.execute("PRAGMA foreign_keys=ON")
    return conn


async def init_db() -> None:
    """Ініціалізує БД: створює таблиці якщо їх немає."""
    conn = await get_connection()
    try:
        await conn.executescript(_CREATE_TABLES_SQL)
        await conn.commit()
        await _migrate_automix_schema(conn)
        logger.info(f"База даних ініціалізована: {DB_PATH}")
    finally:
        await conn.close()
