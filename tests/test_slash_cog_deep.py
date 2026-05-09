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
async def test_cog_load_and_ready_error(cog, bot):
    await cog.cog_load()
    with patch('discord_music_bot.cogs.slash_music_cog.auto_resume', side_effect=Exception("Resume error")):
        with pytest.raises(Exception, match="Resume error"):
            await cog._on_ready_auto_resume()

@pytest.mark.asyncio
async def test_join_move_to(cog, interaction):
    other_channel = Mock()
    interaction.guild.voice_client.channel = other_channel
    await cog.join.callback(cog, interaction)
    interaction.guild.voice_client.move_to.assert_called()

@pytest.mark.asyncio
async def test_play_playlist_error(cog, interaction):
    cog.source_service.extract_playlist.return_value = (None, None)
    await cog.play.callback(cog, interaction, query="http://playlist")
    interaction.followup.send.assert_called_with("❌ Не вдалося завантажити плейлист або він порожній.")

@pytest.mark.asyncio
async def test_play_url_error(cog, interaction):
    cog.source_service.get_video_info.return_value = None
    await cog.play.callback(cog, interaction, query="http://video")
    interaction.followup.send.assert_called_with("❌ Не вдалося знайти трек.")

@pytest.mark.asyncio
async def test_play_no_voice(cog, interaction):
    interaction.user.voice = None
    await cog.play.callback(cog, interaction, query="test")
    interaction.response.send_message.assert_called_with("Зайдіть у голосовий канал!", ephemeral=True)

@pytest.mark.asyncio
async def test_pause_resume_no_playing(cog, interaction):
    interaction.guild.voice_client.is_playing.return_value = False
    interaction.guild.voice_client.is_paused.return_value = False
    await cog.pause.callback(cog, interaction)
    interaction.response.send_message.assert_called_with("Нічого ставити на паузу.", ephemeral=True)
    await cog.resume.callback(cog, interaction)
    interaction.response.send_message.assert_called_with("Нічого відновлювати.", ephemeral=True)

@pytest.mark.asyncio
async def test_stop_and_shuffle_errors(cog, interaction):
    # Stop when no voice client
    interaction.guild.voice_client = None
    await cog.stop.callback(cog, interaction)
    interaction.response.send_message.assert_called_with("Бот не грає.", ephemeral=True)
    
    # Stop when voice client exists
    interaction.guild.voice_client = Mock()
    interaction.guild.voice_client.stop = Mock()
    await cog.stop.callback(cog, interaction)
    interaction.response.send_message.assert_called_with("⏹️ Зупинено.")
    
    # Shuffle error
    cog.queue_service.get_queue.return_value = [1]
    await cog.shuffle.callback(cog, interaction)
    interaction.response.send_message.assert_called_with("Недостатньо треків.", ephemeral=True)

@pytest.mark.asyncio
async def test_volume_validation(cog, interaction):
    # Level 250 should be clamped to 200
    await cog.volume.callback(cog, interaction, level=250)
    interaction.response.send_message.assert_called_with("🔊 Гучність встановлена: **200%**")

@pytest.mark.asyncio
async def test_dj_and_automix_off(cog, interaction):
    await cog.dj.callback(cog, interaction, enabled="off")
    assert cog._dj_settings_cache[123]["enabled"] is False
    await cog.automix.callback(cog, interaction, enabled="off")
    assert cog._automix_enabled[123] is False

@pytest.mark.asyncio
async def test_play_next_song_error_retry(cog):
    guild = Mock(id=123)
    vc = Mock(is_connected=Mock(return_value=True))
    cog.queue_service.get_queue.return_value = [{"title": "Bad"}]
    cog.player_service.play_stream.side_effect = Exception("Play error")
    
    with patch.object(cog, 'play_next_song', side_effect=[None, None]) as mock_play:
        await MusicCog.play_next_song(cog, guild, vc)
        assert mock_play.called

@pytest.mark.asyncio
async def test_on_voice_state_update_leave(cog, bot):
    member = Mock(id=bot.user.id, guild=Mock(id=123))
    before = Mock(channel=Mock())
    after = Mock(channel=None)
    await cog.on_voice_state_update(member, before, after)
    cog.queue_service.clear.assert_called_with(123)
    
    human = Mock(id=777, bot=False, guild=Mock(id=123))
    bot_vc = Mock(channel=before.channel)
    bot_vc.disconnect = AsyncMock()
    bot_vc.is_connected = Mock(return_value=True)
    human.guild.voice_client = bot_vc
    before.channel.members = [member]
    await cog.on_voice_state_update(human, before, after)
    bot_vc.disconnect.assert_called()

@pytest.mark.asyncio
async def test_check_after_play_error(cog):
    guild = Mock(id=123)
    vc = Mock()
    await cog.check_after_play(guild, vc, Exception("After error"))
    cog.logger.error.assert_called()

@pytest.mark.asyncio
async def test_force_voice_cleanup(cog):
    guild = Mock(id=123)
    guild.voice_client = Mock(disconnect=AsyncMock())
    await cog._force_voice_cleanup(guild)
    guild.voice_client.disconnect.assert_called()
