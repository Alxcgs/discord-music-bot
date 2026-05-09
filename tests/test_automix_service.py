import pytest
from unittest.mock import Mock, AsyncMock
from discord_music_bot.services.automix_service import AutomixService, AutomixConfig
from discord_music_bot import consts

@pytest.mark.asyncio
async def test_automix_strategies():
    repo = Mock()
    service = AutomixService(repo)
    
    guild_id = 123
    recent = ["url1"]
    automix_recent = ["url2"]
    penalties = {"url3": 2}
    
    # Mock repository data
    track1 = {"url": "url3", "title": "T3", "play_count": 10}
    track2 = {"url": "url4", "title": "T4", "play_count": 5}
    repo.get_top_tracks = AsyncMock(return_value=[track1, track2])
    repo.get_history = AsyncMock(return_value=[track1, track2])
    
    # Test top_weighted
    res = await service.recommend_for_strategy(
        guild_id, consts.AUTOMIX_STRATEGY_TOP,
        recent_urls=recent, automix_recent_urls=automix_recent, skip_penalties=penalties
    )
    assert res is not None
    assert res["source"] == "automix"
    
    # Test history_explore
    res = await service.recommend_for_strategy(
        guild_id, consts.AUTOMIX_STRATEGY_HISTORY,
        recent_urls=recent, automix_recent_urls=automix_recent, skip_penalties=penalties
    )
    assert res is not None
    assert res["source"] == "automix"

@pytest.mark.asyncio
async def test_automix_fallbacks():
    repo = Mock()
    service = AutomixService(repo)
    
    # Empty repo
    repo.get_top_tracks = AsyncMock(return_value=[])
    repo.get_history = AsyncMock(return_value=[])
    
    res = await service.recommend_for_strategy(
        123, "top_weighted", recent_urls=[], automix_recent_urls=[], skip_penalties={}
    )
    assert res is None

def test_weighted_pick_edge_cases():
    service = AutomixService(Mock())
    assert service._weighted_pick([]) is None
    assert service._weighted_pick([({"t": 1}, 0.0)]) is None
    assert service._weighted_pick([({"t": 1}, 1.0)])["t"] == 1
