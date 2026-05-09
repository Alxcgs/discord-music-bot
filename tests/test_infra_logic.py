import pytest
import os
import aiosqlite
import logging
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from discord_music_bot import utils, config, database, healthcheck
import asyncio
import subprocess

# --- utils.py tests ---

def test_format_duration_edge_cases():
    assert utils.format_duration(-10) == "∞"
    assert utils.format_duration("invalid") == "∞"
    assert utils.format_duration(None) == "∞"
    assert utils.format_duration(3600) == "01:00:00"

# --- config.py tests ---
def test_config_import_and_warning():
    with patch('os.getenv', return_value='dummy_test_token'), \
         patch('logging.warning') as mock_warning:
        import importlib
        import discord_music_bot.config
        importlib.reload(discord_music_bot.config)
        mock_warning.assert_called()
        # For now, just ensure it's imported.
        assert config.DISCORD_TOKEN == 'dummy_test_token'

# --- database.py tests ---
@pytest.mark.asyncio
async def test_database_migration_missing_columns(tmp_path):
    db_file = tmp_path / "migrate.db"
    async with aiosqlite.connect(str(db_file)) as conn:
        # Create tables WITHOUT strategy
        await conn.execute("CREATE TABLE automix_settings (guild_id INTEGER PRIMARY KEY, enabled INTEGER)")
        await conn.execute("CREATE TABLE automix_feedback_events (id INTEGER PRIMARY KEY, guild_id INTEGER, action TEXT)")
        await conn.commit()
        
        await database._migrate_automix_schema(conn)
        
        # Verify columns added
        cur = await conn.execute("PRAGMA table_info(automix_settings)")
        cols = [r[1] for r in await cur.fetchall()]
        assert "strategy" in cols

@pytest.mark.asyncio
async def test_database_migration_error_branches(tmp_path):
    db_file = tmp_path / "test_error.db"
    async with aiosqlite.connect(str(db_file)) as conn:
        # Mock column_names to raise exception
        with patch('discord_music_bot.database.logger') as mock_logger:
            # We can't easily mock conn.execute for internal helper unless we patch the helper
            with patch('discord_music_bot.database.aiosqlite.Connection.execute', side_effect=Exception("Migration Error")):
                await database._migrate_automix_schema(conn)
                assert mock_logger.warning.call_count >= 1

@pytest.mark.asyncio
async def test_init_db_logs(tmp_path):
    db_dir = tmp_path / "data"
    with patch('discord_music_bot.database.DB_DIR', str(db_dir)), \
         patch('discord_music_bot.database.DB_PATH', str(db_dir / "music.db")), \
         patch('discord_music_bot.database.logger') as mock_logger:
        await database.init_db()
        mock_logger.info.assert_called()

# --- healthcheck.py tests ---
@pytest.mark.asyncio
async def test_cleanup_zombie_task_cancelled():
    with patch('discord_music_bot.healthcheck.logger') as mock_logger:
        with patch('asyncio.sleep', side_effect=asyncio.CancelledError()):
            await healthcheck.cleanup_zombie_processes(1)
            mock_logger.info.assert_called_with("Zombie cleanup task cancelled.")

@pytest.mark.asyncio
async def test_cleanup_zombie_general_error():
    with patch('discord_music_bot.healthcheck.logger') as mock_logger:
        # Raise error after one iteration
        sleep_mock = AsyncMock(side_effect=[None, Exception("Cleanup Fail"), asyncio.CancelledError()])
        with patch('asyncio.sleep', sleep_mock), \
             patch('discord_music_bot.healthcheck._kill_zombie_processes', return_value=0):
            await healthcheck.cleanup_zombie_processes(1)
            mock_logger.error.assert_called()

def test_kill_zombie_windows_edge_cases():
    with patch('os.name', 'nt'), \
         patch('subprocess.run') as mock_run:
        # 1. Empty lines
        mock_run.return_value = Mock(stdout=' \n \n ')
        healthcheck._kill_zombie_processes()
        
        # 2. taskkill failure
        mock_run.side_effect = [
            Mock(stdout='"yt-dlp.exe","1234","Running"'),
            Exception("Taskkill failed")
        ]
        healthcheck._kill_zombie_processes()

def test_kill_zombie_linux_edge_cases():
    with patch('os.name', 'posix'), \
         patch('subprocess.run') as mock_run:
        # 1. Empty lines
        mock_run.return_value = Mock(stdout=' \n ')
        healthcheck._kill_zombie_processes()
        
        # 2. process lookup error
        mock_run.return_value = Mock(stdout=' 1234 1 Z yt-dlp')
        with patch('os.kill', side_effect=ProcessLookupError()):
            healthcheck._kill_zombie_processes()

def test_start_zombie_cleanup():
    loop = MagicMock()
    healthcheck.start_zombie_cleanup(loop, 100)
    loop.create_task.assert_called()
