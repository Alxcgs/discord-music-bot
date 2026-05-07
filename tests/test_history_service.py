import pytest
from unittest.mock import AsyncMock, patch
from discord_music_bot.services.history_service import HistoryService
from discord_music_bot.repository import MusicRepository
from discord_music_bot import consts

@pytest.fixture
def mock_repo():
    repo = AsyncMock(spec=MusicRepository)
    repo.add_history_track = AsyncMock()
    repo.pop_last_history_track = AsyncMock()
    repo.clear_history = AsyncMock()
    repo.get_history = AsyncMock()
    return repo

@pytest.fixture
def history_service(mock_repo):
    def mock_ensure_future(coro, *args, **kwargs):
        coro.close()
        
    with patch("discord_music_bot.services.history_service.asyncio.ensure_future", side_effect=mock_ensure_future):
        yield HistoryService(mock_repo)

def test_add_to_history(history_service):
    track = {"title": "Test"}
    history_service.add_to_history(123, track)
    assert history_service._history[123] == [track]

def test_add_to_history_overflow(history_service, monkeypatch):
    monkeypatch.setattr(consts, "MAX_HISTORY_SIZE", 3)
    
    tracks = [{"title": str(i)} for i in range(5)]
    for t in tracks:
        history_service.add_to_history(123, t)
        
    # The last 3 tracks should be kept
    assert len(history_service._history[123]) == 3
    assert history_service._history[123] == [{"title": "2"}, {"title": "3"}, {"title": "4"}]

def test_get_last_track(history_service):
    track1 = {"title": "1"}
    track2 = {"title": "2"}
    history_service.add_to_history(123, track1)
    history_service.add_to_history(123, track2)
    
    last = history_service.get_last_track(123)
    assert last == track2
    assert history_service._history[123] == [track1]

def test_get_last_track_empty(history_service):
    assert history_service.get_last_track(123) is None

def test_clear_history(history_service):
    history_service.add_to_history(123, {"title": "1"})
    history_service.clear_history(123)
    assert history_service._history[123] == []

@pytest.mark.asyncio
async def test_load_from_db(history_service, mock_repo):
    db_history = [{"title": "DB 1", "url": "http://1"}, {"title": "DB 2", "webpage_url": "http://2"}]
    mock_repo.get_history.return_value = db_history
    
    await history_service.load_from_db(123)
    
    # webpage_url is added if missing
    expected = [
        {"title": "DB 1", "url": "http://1", "webpage_url": "http://1"},
        {"title": "DB 2", "webpage_url": "http://2"}
    ]
    assert history_service._history[123] == expected

@pytest.mark.asyncio
async def test_load_from_db_error(history_service, mock_repo):
    mock_repo.get_history.side_effect = Exception("DB Error")
    
    await history_service.load_from_db(123)
    
    assert history_service._history[123] == []
