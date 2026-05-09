import pytest
from unittest.mock import Mock, AsyncMock
from discord_music_bot.services.queue_service import QueueService
from discord_music_bot.services.history_service import HistoryService
from discord_music_bot.services.automix_service import AutomixService
from discord_music_bot.repository import MusicRepository

@pytest.fixture
def mock_repo():
    repo = Mock(spec=MusicRepository)
    repo.get_automix_settings = AsyncMock(return_value={"enabled": True, "strategy": "top_weighted"})
    repo.add_history_track = AsyncMock()
    repo.get_top_tracks = AsyncMock(return_value=[])
    repo.get_history = AsyncMock(return_value=[])
    return repo

@pytest.mark.asyncio
async def test_queue_service(mock_repo):
    service = QueueService(mock_repo)
    service.add_track(123, {"title": "T1"})
    assert service.get_queue(123)[0]["title"] == "T1"
    
    # Test add_track side effects
    service.add_track(123, {"title": "T2"})
    assert len(service.get_queue(123)) == 2

@pytest.mark.asyncio
async def test_history_service(mock_repo):
    service = HistoryService(mock_repo)
    service.add_to_history(123, {"title": "H1"})
    import asyncio
    await asyncio.sleep(0.1)
    mock_repo.add_history_track.assert_called()

@pytest.mark.asyncio
async def test_automix_service(mock_repo):
    service = AutomixService(mock_repo)
    res = await service.recommend_for_strategy(123, "top_weighted", recent_urls=[], automix_recent_urls=[], skip_penalties={})
    assert res is None 
