import pytest
import discord
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from discord_music_bot.views.music_controls import MusicControls, VolumeModal, _MixSettingsView
from discord_music_bot.views.queue_view import QueueView, MoveTrackModal
from discord_music_bot.views.history_view import HistoryView
from discord_music_bot.views.dismiss_view import DismissView
from discord_music_bot.views.search_results_view import SearchResultsView

@pytest.fixture
def mock_cog():
    cog = Mock()
    cog.player_service = Mock()
    cog.history_service = Mock()
    cog.history_service._history = {}
    cog.queue_service = Mock()
    cog.repository = AsyncMock()
    cog.processing_buttons = set()
    cog._automix_enabled = {}
    cog._automix_strategy_mode = {}
    cog._automix_settings_cache = {}
    cog._dj_settings_cache = {}
    cog._fade_seconds = {}
    cog._session_tracks = {}
    cog._guild_volumes = {}
    cog.current_song = {}
    cog.update_player = AsyncMock()
    cog.play_next_song = AsyncMock()
    cog.leave_logic = AsyncMock()
    cog._ensure_dj_state_loaded = AsyncMock()
    cog._ensure_automix_state_loaded = AsyncMock()
    cog.on_skip_automix_feedback = AsyncMock()
    cog.logger = Mock()
    return cog

@pytest.fixture
def mock_interaction(mock_cog):
    interaction = AsyncMock(spec=discord.Interaction)
    interaction.guild = Mock(spec=discord.Guild)
    interaction.guild.id = 123
    interaction.guild.name = "Test Guild"
    interaction.user = Mock()
    interaction.user.voice = Mock()
    interaction.user.voice.channel = Mock()
    interaction.response = AsyncMock()
    interaction.followup = AsyncMock()
    interaction.guild.voice_client = Mock()
    interaction.guild.voice_client.channel = interaction.user.voice.channel
    interaction.client = Mock()
    interaction.client.get_cog.return_value = mock_cog
    interaction.message = AsyncMock()
    return interaction

@pytest.mark.asyncio
async def test_volume_modal_full(mock_interaction):
    vc = Mock()
    vc.source = Mock()
    vc.source.volume = 0.5
    modal = VolumeModal(vc)
    modal.volume_input = Mock()
    modal.volume_input.value = "150"
    
    mock_cog = mock_interaction.client.get_cog.return_value
    mock_cog._guild_volumes = {}
    
    await modal.on_submit(mock_interaction)
    assert vc.source.volume == 1.5

@pytest.mark.asyncio
async def test_mix_settings_view_full(mock_cog, mock_interaction):
    view = _MixSettingsView(mock_cog, 123)
    mock_cog._dj_settings_cache[123] = {"enabled": False}
    # Use class method to avoid bound method issues
    await _MixSettingsView.toggle_dj(view, mock_interaction, Mock())
    assert mock_cog._dj_settings_cache[123]["enabled"] is True
    
    mock_select = Mock()
    mock_select.values = ["funny"]
    await _MixSettingsView.dj_persona_select(view, mock_interaction, mock_select)
    mock_cog.repository.set_dj_persona.assert_called()

@pytest.mark.asyncio
async def test_music_controls_skip(mock_cog, mock_interaction):
    view = MusicControls(mock_cog, mock_interaction.guild)
    mock_interaction.guild.voice_client.is_playing.return_value = True
    await MusicControls.skip_button(view, mock_interaction, view.skip_button)
    mock_interaction.guild.voice_client.stop.assert_called()
    mock_cog.on_skip_automix_feedback.assert_awaited()
