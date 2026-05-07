import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch
import discord
from discord_music_bot.views.music_controls import MusicControls

@pytest.fixture
def mock_cog():
    cog = Mock()
    cog.player_service = Mock()
    cog.history_service = Mock()
    cog.history_service._history = {}
    cog.queue_service = Mock()
    cog.repository = AsyncMock()
    cog.processing_buttons = set()
    cog._skip_after_play = set()
    cog.current_song = {}
    cog.update_player = AsyncMock()
    cog.play_next_song = AsyncMock()
    cog.leave_logic = AsyncMock()
    cog.on_skip_automix_feedback = AsyncMock()
    cog.logger = Mock()
    return cog

@pytest.fixture
def mock_interaction():
    interaction = AsyncMock(spec=discord.Interaction)
    interaction.guild = Mock(spec=discord.Guild)
    interaction.guild.id = 123
    interaction.channel = Mock()
    interaction.channel.id = 456
    interaction.user = Mock()
    interaction.user.voice = Mock()
    interaction.user.voice.channel = Mock()
    interaction.response = AsyncMock()
    interaction.followup = AsyncMock()
    interaction.guild.voice_client = Mock(spec=discord.VoiceClient)
    interaction.guild.voice_client.channel = interaction.user.voice.channel
    return interaction

@pytest.fixture
def view(mock_cog, mock_interaction):
    return MusicControls(mock_cog, mock_interaction.guild)

@pytest.mark.asyncio
async def test_interaction_check_success(view, mock_interaction):
    assert await view.interaction_check(mock_interaction) is True

@pytest.mark.asyncio
async def test_interaction_check_no_voice_client(view, mock_interaction):
    mock_interaction.guild.voice_client = None
    assert await view.interaction_check(mock_interaction) is False
    mock_interaction.response.send_message.assert_awaited_once_with("Бот наразі не в голосовому каналі.", ephemeral=True)

@pytest.mark.asyncio
async def test_interaction_check_wrong_channel(view, mock_interaction):
    mock_interaction.user.voice.channel = Mock() # different channel
    assert await view.interaction_check(mock_interaction) is False
    mock_interaction.response.send_message.assert_awaited_once_with("Ви повинні бути в тому ж голосовому каналі, що й бот.", ephemeral=True)

@pytest.mark.asyncio
async def test_pause_resume_button_pause(view, mock_interaction, mock_cog):
    mock_interaction.guild.voice_client.is_playing.return_value = True
    await view.pause_resume_button.callback(mock_interaction)
    
    mock_interaction.guild.voice_client.pause.assert_called_once()
    mock_interaction.response.defer.assert_awaited_once()
    mock_cog.update_player.assert_awaited_once_with(mock_interaction.guild, mock_interaction.channel)

@pytest.mark.asyncio
async def test_pause_resume_button_resume(view, mock_interaction, mock_cog):
    mock_interaction.guild.voice_client.is_playing.return_value = False
    mock_cog.player_service.is_paused.return_value = True
    await view.pause_resume_button.callback(mock_interaction)
    
    mock_cog.player_service.resume.assert_called_once_with(mock_interaction.guild.voice_client)
    mock_interaction.response.defer.assert_awaited_once()
    mock_cog.update_player.assert_awaited_once_with(mock_interaction.guild, mock_interaction.channel)

@pytest.mark.asyncio
async def test_pause_resume_button_nothing_playing(view, mock_interaction, mock_cog):
    mock_interaction.guild.voice_client.is_playing.return_value = False
    mock_cog.player_service.is_paused.return_value = False
    await view.pause_resume_button.callback(mock_interaction)
    
    mock_interaction.response.send_message.assert_awaited_once_with("Зараз нічого не грає.", ephemeral=True)

@pytest.mark.asyncio
async def test_skip_button(view, mock_interaction, mock_cog):
    mock_interaction.guild.voice_client.is_playing.return_value = True
    await view.skip_button.callback(mock_interaction)
    
    mock_cog.on_skip_automix_feedback.assert_awaited_once_with(123)
    mock_interaction.guild.voice_client.stop.assert_called_once()
    mock_interaction.response.send_message.assert_awaited_once()

@pytest.mark.asyncio
async def test_leave_button(view, mock_interaction, mock_cog):
    mock_interaction.guild.voice_client.is_connected.return_value = True
    with patch.object(view, 'stop') as mock_stop:
        await view.leave_button.callback(mock_interaction)
        mock_cog.leave_logic.assert_awaited_once_with(mock_interaction.guild)
        mock_interaction.response.send_message.assert_awaited_once()
        mock_stop.assert_called_once()

@pytest.mark.asyncio
async def test_previous_button_already_processing(view, mock_interaction, mock_cog):
    mock_cog.processing_buttons.add(123)
    await view.previous_button.callback(mock_interaction)
    mock_interaction.response.send_message.assert_awaited_once_with("Зачекайте, обробляється попередня дія.", ephemeral=True)

@pytest.mark.asyncio
async def test_previous_button_success(view, mock_interaction, mock_cog):
    prev_track = {"title": "Old Song", "url": "http://old"}
    current_track = {"title": "Current Song", "url": "http://cur", "player": Mock()}
    
    mock_cog.history_service._history = {123: [prev_track]}
    mock_cog.history_service.get_last_track.return_value = prev_track
    mock_cog.current_song = {123: current_track}
    
    mock_interaction.guild.voice_client.is_playing.return_value = True
    mock_interaction.guild.voice_client.is_connected.return_value = True

    # Speed up sleep
    with patch("asyncio.sleep", new_callable=AsyncMock):
        await view.previous_button.callback(mock_interaction)
    
    # Assert defer
    mock_interaction.response.defer.assert_awaited_once()
    
    # Assert current pushed front
    assert mock_cog.queue_service.push_front.call_count == 2
    
    # Check what was pushed (current without player, then prev)
    expected_current = {"title": "Current Song", "url": "http://cur"}
    mock_cog.queue_service.push_front.assert_any_call(123, expected_current)
    mock_cog.queue_service.push_front.assert_any_call(123, prev_track)
    
    # Assert current_song cleared
    assert 123 not in mock_cog.current_song
    
    # Assert voice client stopped
    mock_interaction.guild.voice_client.stop.assert_called_once()
    
    # Assert manual play called
    mock_cog.play_next_song.assert_awaited_once_with(mock_interaction.guild, mock_interaction.guild.voice_client)
    
    # Assert state cleared
    assert 123 not in mock_cog._skip_after_play
    assert 123 not in mock_cog.processing_buttons
    mock_interaction.followup.send.assert_awaited()

@pytest.mark.asyncio
async def test_previous_button_no_history(view, mock_interaction, mock_cog):
    mock_cog.history_service._history = {}
    mock_cog.repository.get_history.return_value = []
    
    await view.previous_button.callback(mock_interaction)
    
    mock_interaction.followup.send.assert_awaited_once_with("Немає попередніх треків.", ephemeral=True)
    assert 123 not in mock_cog._skip_after_play
    assert 123 not in mock_cog.processing_buttons
