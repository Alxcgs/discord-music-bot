import pytest
import discord
import asyncio
from unittest.mock import Mock, AsyncMock, patch
from discord_music_bot.views.music_controls import MusicControls, VolumeModal, _MixSettingsView
from discord_music_bot import consts

@pytest.fixture
def mock_cog():
    cog = Mock()
    cog.history_service = Mock()
    cog.queue_service = Mock()
    cog.repository = AsyncMock()
    cog.player_service = Mock()
    cog.current_song = {}
    cog.processing_buttons = set()
    cog._skip_after_play = set()
    cog._automix_enabled = {123: False}
    cog._automix_strategy_mode = {123: "ab_split"}
    cog._automix_settings_cache = {123: {"enabled": False, "strategy": "ab_split"}}
    cog._dj_settings_cache = {123: {"enabled": False, "persona": "chill"}}
    cog._fade_seconds = {123: 0.0}
    cog._session_tracks = {}
    cog.update_player = AsyncMock()
    cog.play_next_song = AsyncMock()
    cog.on_skip_automix_feedback = AsyncMock()
    cog.leave_logic = AsyncMock()
    cog._ensure_dj_state_loaded = AsyncMock()
    cog._ensure_automix_state_loaded = AsyncMock()
    cog.logger = Mock()
    return cog

@pytest.fixture
def mock_interaction():
    interaction = Mock(spec=discord.Interaction)
    interaction.guild.id = 123
    interaction.guild.name = "TestGuild"
    interaction.user.id = 111
    interaction.user.mention = "@user"
    interaction.user.voice = Mock()
    interaction.user.voice.channel = Mock()
    interaction.guild.voice_client = Mock()
    interaction.guild.voice_client.channel = interaction.user.voice.channel
    interaction.guild.voice_client.source = Mock()
    interaction.guild.voice_client.source.volume = 0.5
    interaction.response = Mock()
    interaction.response.send_message = AsyncMock()
    interaction.response.edit_message = AsyncMock()
    interaction.response.send_modal = AsyncMock()
    interaction.response.defer = AsyncMock()
    interaction.followup = Mock()
    interaction.followup.send = AsyncMock()
    interaction.channel = Mock()
    return interaction

@pytest.mark.asyncio
async def test_volume_modal_full(mock_interaction):
    vc = mock_interaction.guild.voice_client
    modal = VolumeModal(vc)
    modal.volume_input = Mock(value="80")
    mock_interaction.client.get_cog.return_value = Mock(_guild_volumes={})
    await modal.on_submit(mock_interaction)
    assert vc.source.volume == 0.8

@pytest.mark.asyncio
async def test_mix_settings_view_full(mock_cog, mock_interaction):
    view = _MixSettingsView(mock_cog, 123)
    await _MixSettingsView.toggle_automix(view, mock_interaction, view.toggle_automix)
    await _MixSettingsView.toggle_dj(view, mock_interaction, view.toggle_dj)
    
    select = Mock()
    select.values = ["top_weighted"]
    await _MixSettingsView.automix_mode_select(view, mock_interaction, select)
    
    select.values = ["funny"]
    await _MixSettingsView.dj_persona_select(view, mock_interaction, select)
    
    select.values = ["8"]
    await _MixSettingsView.fade_select(view, mock_interaction, select)
    
    await _MixSettingsView.close_mix(view, mock_interaction, view.close_mix)

@pytest.mark.asyncio
async def test_music_controls_full(mock_cog, mock_interaction):
    view = MusicControls(mock_cog, mock_interaction.guild)
    assert await view.interaction_check(mock_interaction) is True
    
    mock_cog.history_service.get_last_track.return_value = {"title": "Prev", "url": "url_prev"}
    await MusicControls.previous_button(view, mock_interaction, view.previous_button)
    
    vc = mock_interaction.guild.voice_client
    vc.is_playing.return_value = True
    await MusicControls.pause_resume_button(view, mock_interaction, view.pause_resume_button)
    
    vc.is_playing.return_value = False
    mock_cog.player_service.is_paused.return_value = True
    await MusicControls.pause_resume_button(view, mock_interaction, view.pause_resume_button)
    
    vc.is_playing.return_value = True
    await MusicControls.skip_button(view, mock_interaction, view.skip_button)
    
    await MusicControls.leave_button(view, mock_interaction, view.leave_button)
    
    with patch('discord_music_bot.views.queue_view.QueueView', return_value=Mock(create_embed=Mock())):
        await MusicControls.queue_button(view, mock_interaction, view.queue_button)
    
    await MusicControls.mix_settings_button(view, mock_interaction, view.mix_settings_button)
    
    await MusicControls.volume_button(view, mock_interaction, view.volume_button)
    
    mock_cog.repository.get_history.return_value = [{"title": "H1", "duration": 100}]
    await MusicControls.history_button(view, mock_interaction, view.history_button)
    
    mock_cog._session_tracks[123] = [{"title": "S1", "duration": 100}]
    await MusicControls.stats_button(view, mock_interaction, view.stats_button)
    
    mock_interaction.guild.voice_client = None
    assert await view.interaction_check(mock_interaction) is False
