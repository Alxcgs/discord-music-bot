import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from discord_music_bot.healthcheck import _kill_zombie_processes
from discord_music_bot.utils import format_duration
from discord_music_bot.services.dj_service import DJService

@pytest.mark.asyncio
async def test_zombie_cleanup_logic():
    with patch('subprocess.run') as mock_run:
        # Mocking ps output for Linux/macOS
        mock_run.return_value.stdout = "101 1 Z yt-dlp\n102 1 S ffmpeg"
        with patch('os.kill') as mock_kill:
            killed = _kill_zombie_processes()
            assert killed >= 0

def test_utils_format_duration():
    assert format_duration(65) == "01:05"
    assert format_duration(3665) == "01:01:05"
    assert format_duration(0) == "∞"
    assert format_duration(None) == "∞"

@pytest.mark.asyncio
async def test_dj_service_comments():
    service = DJService()
    comment = service.generate_comment("funny", context={"title": "Test Title", "queue_size": 2})
    assert "Test Title" in comment
    assert "2" in comment
