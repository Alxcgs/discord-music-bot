import os
import tempfile
import pytest
from unittest.mock import patch
from discord_music_bot.repository import MusicRepository
from discord_music_bot.database import init_db

@pytest.fixture
async def temp_db_path():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    # Patch the DB_PATH globally for all database operations during the test
    with patch("discord_music_bot.database.DB_PATH", path):
        await init_db()
        yield path
    
    if os.path.exists(path):
        os.remove(path)
    # Also remove the WAL and SHM files
    if os.path.exists(path + "-wal"):
        os.remove(path + "-wal")
    if os.path.exists(path + "-shm"):
        os.remove(path + "-shm")

@pytest.fixture
def repo(temp_db_path):
    return MusicRepository()

@pytest.mark.asyncio
async def test_guild_state(repo):
    # Load empty
    state = await repo.load_guild_state(1)
    assert state is None

    # Save and Load
    await repo.save_guild_state(
        guild_id=1,
        voice_channel_id=10,
        text_channel_id=20,
        track_url="http://test",
        track_title="Test Track",
        is_paused=True
    )
    
    state = await repo.load_guild_state(1)
    assert state is not None
    assert state["voice_channel_id"] == 10
    assert state["text_channel_id"] == 20
    assert state["current_track_url"] == "http://test"
    assert state["current_track_title"] == "Test Track"
    assert state["is_paused"] == 1

    # Clear state
    await repo.clear_guild_state(1)
    state = await repo.load_guild_state(1)
    # The record exists, but values are cleared to NULL / 0
    assert state["voice_channel_id"] is None
    assert state["current_track_url"] is None
    assert state["is_paused"] == 0

@pytest.mark.asyncio
async def test_get_all_active_guilds(repo):
    await repo.save_guild_state(1, voice_channel_id=10, track_url="http://1")
    await repo.save_guild_state(2, voice_channel_id=None, track_url="http://2") # Inactive
    await repo.save_guild_state(3, voice_channel_id=30, track_url=None) # Inactive

    active = await repo.get_all_active_guilds()
    assert len(active) == 1
    assert active[0]["guild_id"] == 1

@pytest.mark.asyncio
async def test_queue_operations(repo):
    # Ensure foreign key exists
    await repo.save_guild_state(1)
    
    tracks = [
        {"url": "http://1", "title": "Track 1", "duration": 100},
        {"url": "http://2", "title": "Track 2", "duration": 200}
    ]
    
    await repo.save_queue(1, tracks)
    
    loaded = await repo.load_queue(1)
    assert len(loaded) == 2
    assert loaded[0]["url"] == "http://1"
    assert loaded[1]["title"] == "Track 2"
    
    await repo.clear_queue(1)
    assert await repo.load_queue(1) == []

@pytest.mark.asyncio
async def test_history_operations(repo):
    await repo.save_guild_state(1)
    
    track1 = {"url": "http://1", "title": "T1"}
    track2 = {"url": "http://2", "title": "T2"}
    
    await repo.add_history_track(1, track1)
    await repo.add_history_track(1, track2)
    
    history = await repo.get_history(1)
    assert len(history) == 2
    # Ordered by played_at DESC, so T2 should be first
    assert history[0]["url"] == "http://2"
    assert history[1]["title"] == "T1"
    
    last_track = await repo.pop_last_history_track(1)
    assert last_track is not None
    assert last_track["url"] == "http://2"
    
    history_after_pop = await repo.get_history(1)
    assert len(history_after_pop) == 1
    assert history_after_pop[0]["url"] == "http://1"
    
    await repo.clear_history(1)
    assert await repo.get_history(1) == []

@pytest.mark.asyncio
async def test_automix_settings(repo):
    await repo.save_guild_state(1)
    
    # Default is None
    assert await repo.get_automix_enabled(1) is None
    
    await repo.set_automix_enabled(1, True)
    assert await repo.get_automix_enabled(1) is True
    
    settings = await repo.get_automix_settings(1)
    assert settings["enabled"] is True
    assert settings["strategy"] == "ab_split"
    
    await repo.set_automix_strategy(1, "llm_based")
    settings = await repo.get_automix_settings(1)
    assert settings["strategy"] == "llm_based"
