import pytest
import discord
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from discord_music_bot.cogs.slash_music_cog import MusicCog
from discord_music_bot import consts
import asyncio

class MockInteraction(Mock):
    def __init__(self, *args, **kwargs):
        super().__init__(spec=discord.Interaction, *args, **kwargs)
        self.response = AsyncMock(spec=discord.InteractionResponse)
        self.followup = AsyncMock(spec=discord.Webhook)
        self.message = MagicMock(spec=discord.Message)
        self.user = MagicMock(spec=discord.Member)
        self.guild = MagicMock(spec=discord.Guild)
        self.guild.id = 123
        self.guild_id = 123

@pytest.fixture
def cog():
    bot = MagicMock()
    with patch('discord_music_bot.cogs.slash_music_cog.MusicRepository', return_value=AsyncMock()):
        c = MusicCog(bot)
        c.repository = AsyncMock()
        c.queue_service = Mock()
        c.logger = Mock()
        c.update_player = AsyncMock()
        c.current_song = {}
        c._automix_enabled = {}
        c._automix_diversity_recent_picks = {}
        return c

@pytest.mark.asyncio
async def test_cog_stats_history_100(cog):
    i = MockInteraction()
    
    # Coverage for stats command error branch
    cog.repository.get_top_tracks.side_effect = Exception("Fail")
    await MusicCog.stats.callback(cog, i)
    cog.logger.error.assert_called()

    # Coverage for history command error branch
    i = MockInteraction()
    cog.repository.get_history.side_effect = Exception("Fail")
    await MusicCog.history.callback(cog, i)
    cog.logger.error.assert_called()

    # Coverage for move command success
    i = MockInteraction()
    cog.queue_service.get_queue.return_value = [{"title": "T1"}, {"title": "T2"}]
    cog.queue_service.move_track.return_value = {"title": "T1"}
    await MusicCog.move.callback(cog, i, 1, 2)
    i.response.send_message.assert_called()

    # Coverage for leave command
    i = MockInteraction()
    i.guild.voice_client = Mock()
    cog.leave_logic = AsyncMock()
    await MusicCog.leave.callback(cog, i)
    cog.leave_logic.assert_called()

    # Coverage for reset command
    i = MockInteraction()
    i.guild.voice_client = Mock()
    i.guild.voice_client.disconnect = AsyncMock(side_effect=Exception("Disc Fail"))
    await MusicCog.reset.callback(cog, i)
    i.response.send_message.assert_called()
