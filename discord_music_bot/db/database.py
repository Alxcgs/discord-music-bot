"""
Підключення до SQLite через aiosqlite та система міграцій.
"""
import logging
from contextlib import asynccontextmanager
from pathlib import Path

import aiosqlite

logger = logging.getLogger('MusicBot.db')

# Шлях до БД (каталог проекту / data / music_bot.db)
def get_db_path() -> Path:
    base = Path(__file__).resolve().parent.parent.parent
    data_dir = base / 'data'
    data_dir.mkdir(exist_ok=True)
    return data_dir / 'music_bot.db'

# Міграції: кожен елемент — (version, sql)
MIGRATIONS = [
    (1, """
        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER PRIMARY KEY
        );
        INSERT OR IGNORE INTO schema_version (version) VALUES (0);
    """),
    (2, """
        CREATE TABLE IF NOT EXISTS play_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            requester_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            url TEXT,
            webpage_url TEXT,
            duration INTEGER,
            thumbnail TEXT,
            played_at REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_play_history_guild ON play_history(guild_id);
        CREATE INDEX IF NOT EXISTS idx_play_history_played_at ON play_history(played_at DESC);
    """),
    (3, """
        CREATE TABLE IF NOT EXISTS guild_settings (
            guild_id INTEGER PRIMARY KEY,
            volume REAL DEFAULT 0.5,
            settings_json TEXT,
            updated_at REAL
        );
    """),
]


async def _get_version(conn: aiosqlite.Connection) -> int:
    try:
        async with conn.execute("SELECT version FROM schema_version ORDER BY version DESC LIMIT 1") as cur:
            row = await cur.fetchone()
            return int(row[0]) if row else 0
    except aiosqlite.OperationalError:
        return 0


async def _set_version(conn: aiosqlite.Connection, version: int) -> None:
    await conn.execute("DELETE FROM schema_version")
    await conn.execute("INSERT INTO schema_version (version) VALUES (?)", (version,))
    await conn.commit()


async def run_migrations(conn: aiosqlite.Connection) -> None:
    current = await _get_version(conn)
    for version, sql in MIGRATIONS:
        if version <= current:
            continue
        logger.info(f"Running migration {version}")
        for statement in sql.strip().split(';'):
            statement = statement.strip()
            if statement:
                await conn.execute(statement)
        await _set_version(conn, version)
    await conn.commit()


async def init_db() -> None:
    """Створює БД та застосовує міграції."""
    path = get_db_path()
    async with aiosqlite.connect(path) as conn:
        conn.row_factory = aiosqlite.Row
        await run_migrations(conn)
        await conn.commit()
    logger.info(f"Database initialized: {path}")


@asynccontextmanager
async def get_connection():
    """Контекстний менеджер для отримання з'єднання з БД."""
    path = get_db_path()
    conn = await aiosqlite.connect(path)
    conn.row_factory = aiosqlite.Row
    try:
        yield conn
    finally:
        await conn.close()
