import pytest
from unittest.mock import AsyncMock, patch
from discord_music_bot.services.queue_service import QueueService
from discord_music_bot.repository import MusicRepository

@pytest.fixture
def mock_repo():
    repo = AsyncMock(spec=MusicRepository)
    repo.save_queue = AsyncMock()
    repo.load_queue = AsyncMock()
    repo.clear_queue = AsyncMock()
    return repo

@pytest.fixture
def queue_service(mock_repo):
    # Патчимо asyncio.ensure_future, щоб синхронні тести не намагалися
    # запускати таски на відсутньому event loop.
    def mock_ensure_future(coro, *args, **kwargs):
        coro.close()
        
    with patch("discord_music_bot.services.queue_service.asyncio.ensure_future", side_effect=mock_ensure_future):
        yield QueueService(mock_repo)

def test_get_queue_empty(queue_service):
    queue = queue_service.get_queue(123)
    assert queue == []

def test_add_track(queue_service):
    track = {"title": "Test Song", "url": "http://test"}
    queue_service.add_track(123, track)
    assert queue_service.get_queue(123) == [track]

def test_add_tracks(queue_service):
    tracks = [{"title": "1"}, {"title": "2"}]
    queue_service.add_tracks(123, tracks)
    assert queue_service.get_queue(123) == tracks

def test_get_next_track(queue_service):
    track1 = {"title": "1"}
    track2 = {"title": "2"}
    queue_service.add_tracks(123, [track1, track2])
    
    next_track = queue_service.get_next_track(123)
    assert next_track == track1
    assert queue_service.get_queue(123) == [track2]

def test_get_next_track_empty(queue_service):
    assert queue_service.get_next_track(123) is None

def test_clear(queue_service):
    queue_service.add_track(123, {"title": "1"})
    queue_service.clear(123)
    assert queue_service.get_queue(123) == []

def test_shuffle(queue_service):
    tracks = [{"title": str(i)} for i in range(10)]
    queue_service.add_tracks(123, tracks.copy())
    queue_service.shuffle(123)
    # The queue should contain the same elements but likely in a different order
    queue = queue_service.get_queue(123)
    assert len(queue) == 10
    assert sorted([t["title"] for t in queue]) == sorted([t["title"] for t in tracks])

def test_push_front(queue_service):
    queue_service.add_track(123, {"title": "1"})
    queue_service.push_front(123, {"title": "2"})
    assert queue_service.get_queue(123) == [{"title": "2"}, {"title": "1"}]

def test_move_track_valid(queue_service):
    queue_service.add_tracks(123, [{"title": "1"}, {"title": "2"}, {"title": "3"}])
    # Move track at pos 3 (index 2) to pos 1 (index 0)
    moved = queue_service.move_track(123, 3, 1)
    assert moved == {"title": "3"}
    assert queue_service.get_queue(123) == [{"title": "3"}, {"title": "1"}, {"title": "2"}]

def test_move_track_same_position(queue_service):
    queue_service.add_tracks(123, [{"title": "1"}, {"title": "2"}])
    moved = queue_service.move_track(123, 2, 2)
    assert moved == {"title": "2"}
    assert queue_service.get_queue(123) == [{"title": "1"}, {"title": "2"}]

def test_move_track_invalid_positions(queue_service):
    queue_service.add_track(123, {"title": "1"})
    assert queue_service.move_track(123, 0, 1) is None
    assert queue_service.move_track(123, 1, 5) is None
    assert queue_service.get_queue(123) == [{"title": "1"}]

def test_peek_next(queue_service):
    track = {"title": "1"}
    queue_service.add_track(123, track)
    assert queue_service.peek_next(123) == track
    # ensure it wasn't removed
    assert queue_service.get_queue(123) == [track]

@pytest.mark.asyncio
async def test_load_from_db(queue_service, mock_repo):
    db_queue = [{"title": "DB Track"}]
    mock_repo.load_queue.return_value = db_queue
    
    await queue_service.load_from_db(123)
    
    assert queue_service.get_queue(123) == db_queue
    mock_repo.load_queue.assert_awaited_once_with(123)

@pytest.mark.asyncio
async def test_load_from_db_error(queue_service, mock_repo):
    mock_repo.load_queue.side_effect = Exception("DB Error")
    
    await queue_service.load_from_db(123)
    
    # Upon error, it should default to empty list
    assert queue_service.get_queue(123) == []
