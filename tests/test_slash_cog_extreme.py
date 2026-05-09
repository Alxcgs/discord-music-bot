import pytest
import discord
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from discord_music_bot.cogs.slash_music_cog import MusicCog
from discord_music_bot import consts
import asyncio

@pytest.fixture
def bot():
    b = Mock(spec=discord.Client)
    b.user = Mock(id=999)
    b.add_listener = Mock()
    b.get_channel = Mock()
    b.loop = MagicMock()
    b.add_cog = Mock()
    return b

@pytest.fixture
def cog(bot):
    with patch('discord_music_bot.cogs.slash_music_cog.MusicRepository', return_value=MagicMock()):
        c = MusicCog(bot)
        c.repository = AsyncMock()
        c.repository.get_automix_skip_penalties = AsyncMock(return_value={})
        c.repository.get_automix_settings = AsyncMock(return_value={"enabled": 1, "strategy": "top_weighted"})
        c.repository.get_dj_settings = AsyncMock(return_value=None)
        c.repository.save_guild_state = AsyncMock()
        c.queue_service = Mock()
        c.queue_service.get_queue.return_value = []
        c.history_service = Mock()
        c.player_service = Mock()
        c.player_service.play_stream = AsyncMock()
        c.player_service.is_playing = Mock()
        c.player_service.is_paused = Mock()
        c.automix_service = Mock()
        c.automix_service.recommend_for_strategy = AsyncMock()
        c.dj_service = Mock()
        c.dj_service.generate_comment = AsyncMock()
        c.source_service = Mock()
        c.source_service.extract_playlist = AsyncMock()
        c.source_service.get_video_info = AsyncMock()
        c.source_service.search_videos = AsyncMock()
        c.logger = Mock()
        return c

@pytest.fixture
def interaction():
    i = Mock(spec=discord.Interaction)
    i.guild = Mock(spec=discord.Guild)
    i.guild.id = 123
    i.guild.name = "TestGuild"
    i.guild_id = 123
    i.user = Mock(spec=discord.Member)
    i.user.id = 111
    i.user.mention = "@user"
    i.user.voice = Mock()
    i.user.voice.channel = Mock()
    i.user.voice.channel.connect = AsyncMock()
    i.guild.voice_client = Mock()
    i.guild.voice_client.channel = i.user.voice.channel
    i.guild.voice_client.disconnect = AsyncMock()
    i.guild.voice_client.move_to = AsyncMock()
    i.guild.voice_client.stop = Mock()
    i.guild.voice_client.is_playing = Mock(return_value=False)
    i.guild.voice_client.is_paused = Mock(return_value=False)
    i.guild.voice_client.is_connected = Mock(return_value=True)
    i.guild.voice_client.source = Mock()
    i.guild.voice_client.source.volume = 1.0
    i.response = Mock()
    i.response.send_message = AsyncMock()
    i.response.defer = AsyncMock()
    i.response.edit_message = AsyncMock()
    i.followup = Mock()
    i.followup.send = AsyncMock()
    i.channel = Mock()
    i.channel.id = 456
    return i

@pytest.mark.asyncio
async def test_ensure_automix_state_variations(cog):
    cog.repository.get_automix_settings.return_value = {"enabled": 1, "strategy": "invalid_strat"}
    await cog._ensure_automix_state_loaded(123)
    assert cog._automix_settings_cache[123]["strategy"] == consts.AUTOMIX_STRATEGY_DEFAULT
    
    cog._automix_settings_cache = {}
    cog.repository.get_automix_settings.side_effect = Exception("DB Fail")
    await cog._ensure_automix_state_loaded(125)
    cog.logger.warning.assert_called()

@pytest.mark.asyncio
async def test_ensure_dj_state_variations(cog):
    cog.repository.get_dj_settings.return_value = {"enabled": 1, "persona": "funny"}
    await cog._ensure_dj_state_loaded(123)
    assert cog._dj_settings_cache[123]["persona"] == "funny"
    
    cog._dj_settings_cache = {}
    cog.repository.get_dj_settings.side_effect = Exception("DJ Fail")
    await cog._ensure_dj_state_loaded(125)
    assert cog._dj_settings_cache[125]["enabled"] == consts.DJ_DEFAULT_ENABLED

@pytest.mark.asyncio
async def test_maybe_send_dj_comment(cog):
    guild = Mock(id=123)
    cog._dj_settings_cache[123] = {"enabled": True, "persona": "funny"}
    cog._dj_tracks_since_comment[123] = 1 
    cog.player_channels[123] = 456
    channel = AsyncMock()
    cog.bot.get_channel.return_value = channel
    cog.dj_service.generate_comment.return_value = "Nice song!"
    cog.queue_service.get_queue.return_value = []
    
    await cog._maybe_send_dj_comment(guild, {"title": "Test Track"})
    channel.send.assert_called()
    assert cog._dj_tracks_since_comment[123] == 0

@pytest.mark.asyncio
async def test_update_player_with_old_message(cog):
    guild = Mock(id=123)
    channel = AsyncMock()
    cog.control_messages[123] = 789
    old_msg = AsyncMock()
    channel.fetch_message.return_value = old_msg
    cog.queue_service.get_queue.return_value = []
    
    with patch('discord.Embed'), patch('discord_music_bot.views.music_controls.MusicControls', return_value=Mock(spec=discord.ui.View)):
        await cog.update_player(guild, channel)
        old_msg.delete.assert_called()

@pytest.mark.asyncio
async def test_ensure_voice_connected_reconnect(cog):
    guild = Mock(id=123, name="Guild")
    vc = Mock(is_connected=Mock(return_value=False))
    vc.channel = Mock()
    vc.channel.connect = AsyncMock()
    
    new_vc = Mock(is_connected=Mock(return_value=True))
    vc.channel.connect.return_value = new_vc
    result = await cog._ensure_voice_connected(vc, guild)
    assert result == new_vc
    
    vc.channel.connect.side_effect = Exception("Connect failed")
    result = await cog._ensure_voice_connected(vc, guild)
    assert result is None

@pytest.mark.asyncio
async def test_play_next_song_complex(cog):
    guild = Mock(id=123)
    vc = Mock(is_connected=Mock(return_value=True))
    vc.channel = Mock()
    cog.queue_service.get_next_track.return_value = {"title": "Track", "url": "url"}
    cog._fade_seconds[123] = 20
    cog._guild_volumes[123] = 0.8
    
    player = Mock(title="Track", url="url", thumbnail="thumb", duration=100)
    cog.player_service.play_stream.return_value = player
    
    await MusicCog.play_next_song(cog, guild, vc)
    assert player.volume == 0.8
    cog.player_service.play_stream.assert_called()

@pytest.mark.asyncio
async def test_search_command_flow(cog, interaction):
    cog.source_service.search_videos.return_value = [{"title": "Result 1", "url": "url1"}]
    # SearchResultsView might need a real-ish initialization
    with patch('discord_music_bot.views.search_results_view.SearchResultsView', return_value=Mock(spec=discord.ui.View)):
        await cog.search.callback(cog, interaction, query="test")
        interaction.followup.send.assert_called()

@pytest.mark.asyncio
async def test_automix_skip_feedback(cog):
    guild_id = 123
    track_url = "http://test"
    cog._automix_enabled[guild_id] = True
    cog.current_song[guild_id] = {"url": track_url, "source": "automix"}
    
    await cog.on_skip_automix_feedback(guild_id)
    # Check if call was made with these args
    found = False
    for call in cog.repository.add_automix_feedback.call_args_list:
        if call.args == (guild_id, track_url, "skipped"):
            found = True
    assert found

@pytest.mark.asyncio
async def test_setup_function(bot):
    from discord_music_bot.cogs.slash_music_cog import setup
    # Mock bot.add_cog to avoid real cog initialization errors
    await setup(bot)
    bot.add_cog.assert_called()
