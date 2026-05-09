import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from discord_music_bot.services.auto_resume import auto_resume
from discord_music_bot import consts
from datetime import datetime, timezone, timedelta

@pytest.fixture
def bot():
    b = Mock()
    b.get_guild = Mock()
    return b

@pytest.fixture
def cog():
    c = Mock()
    c.repository = AsyncMock()
    c.queue_service = Mock()
    c.player_channels = {}
    c.play_next_song = AsyncMock()
    c.update_player = AsyncMock()
    return c

@pytest.mark.asyncio
async def test_auto_resume_staleness_error(bot, cog):
    cog.repository.get_all_active_guilds.return_value = [
        {'guild_id': 123, 'updated_at': 'invalid-date'}
    ]
    with patch('discord_music_bot.services.auto_resume.logger') as mock_logger:
        await auto_resume(bot, cog)
        mock_logger.warning.assert_called() # Line 51

@pytest.mark.asyncio
async def test_auto_resume_voice_channel_missing(bot, cog):
    guild = Mock()
    guild.get_channel.return_value = None # Voice missing
    bot.get_guild.return_value = guild
    cog.repository.get_all_active_guilds.return_value = [
        {'guild_id': 123, 'voice_channel_id': 456, 'text_channel_id': 789, 'current_track_url': 'test'}
    ]
    await auto_resume(bot, cog)
    cog.repository.clear_guild_state.assert_called_with(123) # Line 68

@pytest.mark.asyncio
async def test_auto_resume_critical_error(bot, cog):
    cog.repository.get_all_active_guilds.side_effect = Exception("Critical DB Error")
    with patch('discord_music_bot.services.auto_resume.logger') as mock_logger:
        await auto_resume(bot, cog)
        mock_logger.error.assert_called() # Line 119

@pytest.mark.asyncio
async def test_auto_resume_failure_for_guild(bot, cog):
    # Triggers line 114
    bot.get_guild.side_effect = Exception("Guild Fetch Fail")
    cog.repository.get_all_active_guilds.return_value = [{'guild_id': 123, 'voice_channel_id': 456, 'text_channel_id': 789, 'current_track_url': 'test'}]
    await auto_resume(bot, cog)
    cog.repository.clear_guild_state.assert_called_with(123)
