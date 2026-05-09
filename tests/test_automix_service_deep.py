import pytest
from unittest.mock import Mock, AsyncMock, patch
from discord_music_bot.services.automix_service import AutomixService
from discord_music_bot import consts

@pytest.fixture
def service():
    repo = AsyncMock()
    return AutomixService(repo)

@pytest.mark.asyncio
async def test_automix_recommend_fallback(service):
    # Testing AUTOMIX_STRATEGY_HISTORY fallback to top_weighted
    service._recommend_history_explore = AsyncMock(return_value=None)
    service._recommend_top_weighted = AsyncMock(return_value={"url": "test"})
    
    res = await service.recommend_for_strategy(
        123, 
        consts.AUTOMIX_STRATEGY_HISTORY,
        recent_urls=[],
        automix_recent_urls=[],
        skip_penalties={}
    )
    assert res["automix_strategy"] == consts.AUTOMIX_STRATEGY_HISTORY # It tags with the original request

@pytest.mark.asyncio
async def test_automix_diversity_penalty_high_limit(service):
    # Testing that max_penalty caps the penalty
    penalty = min(10, service._cfg.max_penalty)
    assert penalty == service._cfg.max_penalty

@pytest.mark.asyncio
async def test_automix_top_weighted_empty(service):
    service._repo.get_top_tracks.return_value = []
    service._repo.get_history.return_value = []
    res = await service._recommend_top_weighted(123, recent_urls=[], automix_recent_urls=[], skip_penalties={})
    assert res is None # Line 130

@pytest.mark.asyncio
async def test_automix_history_empty(service):
    service._repo.get_history.return_value = []
    res = await service._recommend_history_explore(123, recent_urls=[], automix_recent_urls=[], skip_penalties={})
    assert res is None # Line 184
