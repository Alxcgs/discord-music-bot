import pytest
import discord
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from discord_music_bot.cogs.slash_music_cog import MusicCog
from discord_music_bot import consts
import asyncio

def create_robust_interaction():
    i = MagicMock()
    i.guild.id = 123
    i.guild_id = 123
    i.user.id = 111
    i.response.send_message = AsyncMock()
    i.response.defer = AsyncMock()
    i.followup.send = AsyncMock()
    i.response.edit_message = AsyncMock()
    return i

@pytest.fixture
def mock_cog():
    bot = MagicMock()
    with patch('discord_music_bot.cogs.slash_music_cog.MusicRepository', return_value=AsyncMock()):
        cog = MusicCog(bot)
        cog.repository = AsyncMock()
        cog.queue_service = Mock()
        cog.update_player = AsyncMock()
        cog.logger = Mock()
        cog.current_song = {}
        cog.leave_logic = AsyncMock()
        return cog

@pytest.mark.asyncio
async def test_cog_commands_robust(mock_cog):
    i = create_robust_interaction()
    
    # Stats success
    mock_cog.repository.get_top_tracks.return_value = [{"title": "T", "play_count": 1}]
    mock_cog.repository.get_total_listening_time.return_value = 10
    mock_cog.repository.get_listening_stats.return_value = {"total_tracks": 1, "unique_tracks": 1, "total_seconds": 1}
    await mock_cog.stats.callback(mock_cog, i)
    i.followup.send.assert_called()

    # Stats error
    mock_cog.repository.get_top_tracks.side_effect = Exception("Fail")
    await mock_cog.stats.callback(mock_cog, i)
    
    # History success
    i = create_robust_interaction()
    mock_cog.repository.get_history.return_value = [{"title": "T", "duration": 1, "played_at": "2026-01-01"}]
    await mock_cog.history.callback(mock_cog, i)
    i.followup.send.assert_called()

    # History error
    mock_cog.repository.get_history.side_effect = Exception("Fail")
    await mock_cog.history.callback(mock_cog, i)
