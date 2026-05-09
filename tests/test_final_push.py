import pytest
import discord
from unittest.mock import Mock, AsyncMock, patch, MagicMock, PropertyMock
from discord_music_bot.cogs.slash_music_cog import MusicCog
from discord_music_bot.services.auto_resume import auto_resume
from discord_music_bot import consts
import main
import asyncio

@pytest.fixture
def mock_interaction():
    i = MagicMock()
    i.guild.id = 123
    i.guild_id = 123
    i.user.id = 111
    i.channel.id = 456
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
        cog._automix_enabled = {}
        cog._dj_settings_cache = {}
        return cog

@pytest.mark.asyncio
async def test_cog_stats_command_error(mock_cog, mock_interaction):
    # Stats error branch (line 988)
    mock_cog.repository.get_top_tracks.side_effect = Exception("DB Fail")
    await mock_cog.stats.callback(mock_cog, mock_interaction)
    mock_cog.logger.error.assert_called()

@pytest.mark.asyncio
async def test_cog_history_command_error(mock_cog, mock_interaction):
    # History error branch (line 1030)
    mock_cog.repository.get_history.side_effect = Exception("DB Fail")
    await mock_cog.history.callback(mock_cog, mock_interaction)
    mock_cog.logger.error.assert_called()

@pytest.mark.asyncio
async def test_auto_resume_voice_not_found(mock_cog):
    bot = MagicMock()
    guild = MagicMock()
    guild.get_channel.return_value = None # Voice channel missing
    bot.get_guild.return_value = guild
    with patch('discord_music_bot.database.get_connection', AsyncMock()):
        mock_cog.repository.get_all_active_guilds.return_value = [{'guild_id': 123, 'voice_channel_id': 456, 'text_channel_id': 789, 'current_track_url': 'test'}]
    await auto_resume(bot, mock_cog)
    mock_cog.repository.clear_guild_state.assert_called_with(123) # Line 68

@pytest.mark.asyncio
async def test_main_error_handlers():
    ctx = MagicMock()
    ctx.command.name = "test"
    ctx.send = AsyncMock()
    
    # MissingRequiredArgument
    from discord.ext import commands
    error = commands.MissingRequiredArgument(Mock(name="arg"))
    await main.on_command_error(ctx, error)
    ctx.send.assert_called()
    
    # CheckFailure
    await main.on_command_error(ctx, commands.CheckFailure())
    ctx.send.assert_called()
    
    # CommandInvokeError
    await main.on_command_error(ctx, commands.CommandInvokeError(Exception("Internal")))

@pytest.mark.asyncio
async def test_main_on_ready_sync_error():
    with patch('main.bot') as mock_bot:
        # Mock configure user
        type(mock_bot).user = PropertyMock(return_value=Mock(name="TestBot", id=123))
        mock_bot.tree.sync = AsyncMock(side_effect=Exception("Sync Error"))
        with patch('main.load_cogs', AsyncMock()), \
             patch.object(main.bot, 'change_presence', AsyncMock()):
            await main.on_ready() # Line 161

def test_main_load_cogs_exception():
    with patch('os.listdir', return_value=['fail.py']), \
         patch.object(main.bot, 'load_extension', side_effect=Exception("Load Fail")):
        asyncio.run(main.load_cogs()) # Line 171
