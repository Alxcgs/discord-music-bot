import pytest
from unittest.mock import Mock, AsyncMock, patch
from discord_music_bot.services.queue_service import QueueService

@pytest.fixture
def service():
    repo = AsyncMock()
    return QueueService(repo)

def test_queue_service_push_front_new_guild(service):
    # line 64
    service.push_front(999, {"title": "T1"})
    assert len(service._queues[999]) == 1

def test_queue_service_move_track_empty(service):
    # line 73
    assert service.move_track(999, 1, 2) is None

def test_queue_service_peek_next_empty(service):
    # line 90
    assert service.peek_next(999) is None

@pytest.mark.asyncio
async def test_queue_service_persist_error(service):
    # line 100
    service._repo.save_queue.side_effect = Exception("DB Error")
    with patch('discord_music_bot.services.queue_service.logger') as mock_logger:
        await service._persist_queue(123)
        mock_logger.error.assert_called()
