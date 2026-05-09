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
    
    res = await service.recommend_for_strategy(123, consts.AUTOMIX_STRATEGY_HISTORY)
    assert res["automix_strategy"] == consts.AUTOMIX_STRATEGY_HISTORY # It tags with the original request

@pytest.mark.asyncio
async def test_automix_diversity_penalty_high_limit(service):
    # Testing _get_diversity_penalty with index >= len(penalties)
    p = service._get_diversity_penalty(100, [1, 2, 3])
    assert p == 3 # Should return last penalty

@pytest.mark.asyncio
async def test_automix_top_weighted_empty(service):
    service.repository.get_top_tracks_for_automix.return_value = []
    res = await service._recommend_top_weighted(123)
    assert res is None # Line 130

@pytest.mark.asyncio
async def test_automix_history_empty(service):
    service.repository.get_history_for_automix.return_value = []
    res = await service._recommend_history_explore(123)
    assert res is None # Line 184
