import pytest
import asyncio
import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch
import discord
from discord_music_bot.cogs.slash_music_cog import MusicCog
from discord_music_bot.database import init_db
from discord_music_bot import consts

@pytest.fixture
def mock_bot():
    bot = MagicMock()
    try:
        bot.loop = asyncio.get_running_loop()
    except RuntimeError:
        bot.loop = asyncio.new_event_loop()
    
    mock_channel = MagicMock()
    mock_channel.send = AsyncMock()
    bot.get_channel.return_value = mock_channel
    return bot

@pytest.fixture
async def temp_db():
    fd, path = tempfile.mkstemp()
    os.close(fd)
    with patch('discord_music_bot.database.DB_PATH', path):
        await init_db()
        yield path
    if os.path.exists(path):
        try:
            os.remove(path)
        except: pass

@pytest.fixture
def mock_interaction():
    interaction = MagicMock()
    interaction.guild_id = 123
    
    guild = MagicMock()
    guild.id = 123
    interaction.guild = guild
    
    user = MagicMock()
    user.id = 111
    user.bot = False
    user.display_name = "TestUser"
    user.voice = MagicMock()
    user.voice.channel = MagicMock()
    user.voice.channel.id = 456
    user.voice.channel.name = "Music Channel"
    user.voice.channel.members = [user]
    user.voice.channel.connect = AsyncMock()
    interaction.user = user
    
    channel = MagicMock()
    channel.id = 789
    channel.send = AsyncMock()
    interaction.channel = channel
    
    mock_voice_client = MagicMock()
    mock_voice_client.channel = user.voice.channel
    mock_voice_client.guild = guild
    mock_voice_client.stop = MagicMock()
    mock_voice_client.is_connected = MagicMock(return_value=True)
    mock_voice_client.is_playing = MagicMock(return_value=False)
    mock_voice_client.is_paused = MagicMock(return_value=False)
    mock_voice_client.disconnect = AsyncMock()
    
    guild.voice_client = None
    user.voice.channel.connect.return_value = mock_voice_client
    
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()
    interaction.response.defer = AsyncMock()
    interaction.followup = MagicMock()
    interaction.followup.send = AsyncMock()
    
    return interaction

@pytest.fixture
async def cog(mock_bot, temp_db):
    with patch('discord_music_bot.database.DB_PATH', temp_db):
        cog = MusicCog(mock_bot)
        
        # Використовуємо реальні корутини для фонових задач репозиторію
        async def empty_coro(*args, **kwargs):
            await asyncio.sleep(0)
            
        cog.repository.add_automix_feedback_event = MagicMock(side_effect=empty_coro)
        cog.repository.add_history_track = MagicMock(side_effect=empty_coro)
        
        await cog.repository.save_guild_state(123, 456, 789)
        
        cog.source_service = AsyncMock()
        cog.player_service = MagicMock()
        
        async def mock_play_stream(*args, **kwargs):
            track_dict = args[1] if len(args) > 1 else {}
            url = track_dict.get('url', '')
            mock_player = MagicMock()
            mock_player.url = url
            mock_player.title = track_dict.get('title', 'Test Track')
            mock_player.duration = 180
            mock_player.thumbnail = "thumb.jpg"
            return mock_player
            
        cog.player_service.play_stream = AsyncMock(side_effect=mock_play_stream)
        cog.player_service.is_playing = MagicMock(return_value=False)
        cog.player_service.is_paused = MagicMock(return_value=False)
        
        cog.update_player = AsyncMock()
        cog.dj_service = MagicMock()
        cog.dj_service.comment_track = AsyncMock()
        cog.dj_service.get_persona = MagicMock(return_value="default")
        
        cog._auto_resume_executed = True
        return cog

@pytest.mark.asyncio
async def test_integration_play_flow(cog, mock_interaction):
    query = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    track_info = {
        'title': 'Never Gonna Give You Up',
        'url': query,
        'webpage_url': query,
        'duration': 212,
        'thumbnail': 'thumb_url'
    }
    cog.source_service.get_video_info.return_value = track_info
    
    await cog.play.callback(cog, mock_interaction, query)
    
    cog.player_service.play_stream.assert_called()
    assert cog.current_song[123]['title'] == 'Never Gonna Give You Up'

@pytest.mark.asyncio
async def test_integration_skip_flow(cog, mock_interaction):
    guild_id = 123
    mock_voice_client = await mock_interaction.user.voice.channel.connect()
    mock_voice_client.is_playing.return_value = True
    mock_interaction.guild.voice_client = mock_voice_client
    
    cog.current_song[guild_id] = {
        'title': 'Current Song',
        'url': 'url1',
        'player': MagicMock()
    }
    
    next_track = {'title': 'Next Song', 'url': 'url2', 'requester': mock_interaction.user}
    cog.queue_service.add_track(guild_id, next_track)
    
    await cog.skip.callback(cog, mock_interaction)
    mock_voice_client.stop.assert_called_once()
    
    await cog.play_next_song(mock_interaction.guild, mock_voice_client)
    assert cog.current_song[guild_id]['title'] == 'Next Song'

@pytest.mark.asyncio
async def test_integration_automix_activation(cog, mock_interaction):
    guild_id = 123
    cog._automix_enabled[guild_id] = True
    cog._automix_strategy_mode[guild_id] = "top_weighted"
    cog.player_channels[guild_id] = 789
    
    mock_voice_client = MagicMock()
    mock_voice_client.is_connected.return_value = True
    mock_voice_client.channel = mock_interaction.user.voice.channel
    
    cog.queue_service.clear(guild_id)
    cog.current_song[guild_id] = {'title': 'Last Song', 'url': 'url0'}
    
    rec_track = {'title': 'Recommended', 'url': 'url_rec', 'source': 'automix'}
    with patch.object(cog.automix_service, 'recommend_for_strategy', new_callable=AsyncMock) as mock_rec:
        mock_rec.return_value = rec_track
        await cog.play_next_song(mock_interaction.guild, mock_voice_client)
    
    assert 123 in cog.current_song
    assert cog.current_song[guild_id]['title'] == 'Recommended'
