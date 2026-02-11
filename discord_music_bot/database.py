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
    FOREIGN KEY (guild_id) REFERENCES guild_state(guild_id) ON DELETE CASCADE
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
    FOREIGN KEY (guild_id) REFERENCES guild_state(guild_id) ON DELETE CASCADE
);

-- Індекс для швидкого отримання історії по guild_id
CREATE INDEX IF NOT EXISTS idx_history_guild_played ON history_tracks(guild_id, played_at DESC);
"""


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
        logger.info(f"База даних ініціалізована: {DB_PATH}")
    finally:
        await conn.close()
