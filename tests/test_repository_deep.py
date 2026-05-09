import pytest
import os
import tempfile
from unittest.mock import patch
from discord_music_bot.repository import MusicRepository
from discord_music_bot.database import init_db

@pytest.fixture
async def repo():
    fd, path = tempfile.mkstemp()
    os.close(fd)
    with patch('discord_music_bot.database.DB_PATH', path):
        await init_db()
        yield MusicRepository()
    if os.path.exists(path):
        os.remove(path)

@pytest.mark.asyncio
async def test_repository_all_methods(repo):
    guild_id = 123
    
    # Guild State
    await repo.save_guild_state(guild_id, voice_channel_id=456, track_url="u1")
    state = await repo.load_guild_state(guild_id)
    assert state["voice_channel_id"] == 456
    
    active = await repo.get_all_active_guilds()
    assert len(active) == 1
    
    await repo.clear_guild_state(guild_id)
    state = await repo.load_guild_state(guild_id)
    assert state["voice_channel_id"] is None
    
    # Queue
    tracks = [{"url": "q1", "title": "T1"}, {"url": "q2", "title": "T2"}]
    await repo.save_queue(guild_id, tracks)
    queue = await repo.load_queue(guild_id)
    assert len(queue) == 2
    
    await repo.clear_queue(guild_id)
    queue = await repo.load_queue(guild_id)
    assert len(queue) == 0
    
    # History
    await repo.add_history_track(guild_id, {"url": "h1", "title": "TH1", "duration": 100})
    await repo.add_history_track(guild_id, {"url": "h2", "title": "TH2", "duration": 200})
    history = await repo.get_history(guild_id)
    assert len(history) == 2
    
    top = await repo.get_top_tracks(guild_id)
    assert len(top) >= 1
    
    total_time = await repo.get_total_listening_time(guild_id)
    assert total_time == 300
    
    stats = await repo.get_listening_stats(guild_id)
    assert stats["total_tracks"] == 2
    
    search = await repo.search_history(guild_id, "TH1")
    assert len(search) == 1
    
    pop = await repo.pop_last_history_track(guild_id)
    assert pop["url"] == "h2"
    
    # Automix Settings
    await repo.set_automix_enabled(guild_id, True)
    settings = await repo.get_automix_settings(guild_id)
    assert settings["enabled"] is True
    
    await repo.set_automix_strategy(guild_id, "top_weighted")
    settings = await repo.get_automix_settings(guild_id)
    assert settings["strategy"] == "top_weighted"
    
    # Penalties
    await repo.increment_automix_skip(guild_id, "bad_url")
    penalties = await repo.get_automix_skip_penalties(guild_id)
    assert penalties["bad_url"] == 1
    
    # Feedback Events
    await repo.add_automix_feedback_event(guild_id, "recommended", "u1", "strat1")
    counts = await repo.get_automix_feedback_counts(guild_id)
    assert counts["recommended"] == 1
    
    ab = await repo.get_automix_ab_comparison(guild_id)
    assert len(ab) == 1
    
    div = await repo.get_automix_diversity_stats(guild_id)
    assert div["rec_total"] == 1
    
    # DJ Settings
    await repo.set_dj_enabled(guild_id, True)
    dj = await repo.get_dj_settings(guild_id)
    assert dj["enabled"] is True
    
    await repo.set_dj_persona(guild_id, "funny")
    dj = await repo.get_dj_settings(guild_id)
    assert dj["persona"] == "funny"
    
    await repo.add_dj_event(guild_id, "commented", message="Hello")
    
    await repo.clear_history(guild_id)
    history = await repo.get_history(guild_id)
    assert len(history) == 0
