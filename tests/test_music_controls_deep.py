import pytest
import discord
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from discord_music_bot.views.music_controls import MusicControls, VolumeModal, _MixSettingsView
from discord_music_bot import consts
import asyncio

@pytest.fixture
def interaction():
    i = Mock(spec=discord.Interaction)
    i.guild = Mock(spec=discord.Guild)
    i.guild.id = 123
    i.guild.voice_client = Mock()
    i.user = Mock(spec=discord.Member)
    i.user.mention = "@user"
    i.user.voice = Mock()
    i.user.voice.channel = i.guild.voice_client.channel
    i.response = Mock()
    i.response.send_message = AsyncMock()
    i.response.edit_message = AsyncMock()
    i.response.defer = AsyncMock()
    i.response.send_modal = AsyncMock()
    i.followup = Mock()
    i.followup.send = AsyncMock()
    i.client = Mock()
    i.client.get_cog = Mock()
    i.channel = Mock()
    return i

@pytest.fixture
def cog():
    c = Mock()
    c.update_player = AsyncMock()
    c.repository = AsyncMock()
    c.history_service = Mock()
    c.queue_service = Mock()
    c.player_service = Mock()
    c.processing_buttons = set()
    c.current_song = {}
    c._session_tracks = {}
    c._automix_enabled = {}
    c._automix_settings_cache = {}
    c._automix_strategy_mode = {}
    c._dj_settings_cache = {}
    c._fade_seconds = {}
    c._skip_after_play = set()
    c._guild_volumes = {}
    c.logger = Mock()
    c._ensure_dj_state_loaded = AsyncMock()
    c._ensure_automix_state_loaded = AsyncMock()
    return c

@pytest.mark.asyncio
async def test_volume_modal_error(interaction):
    vc = Mock()
    vc.source = Mock()
    vc.source.volume = 0.5 # Float value
    modal = VolumeModal(vc)
    modal.volume_input = Mock(value="invalid")
    await VolumeModal.on_submit(modal, interaction)
    interaction.response.send_message.assert_called_with("❌ Введіть число від 0 до 200.", ephemeral=True)

@pytest.mark.asyncio
async def test_mix_settings_bump_error(cog, interaction):
    view = _MixSettingsView(cog, 123)
    cog.update_player.side_effect = Exception("Bump error")
    await view._bump_player(interaction)

@pytest.mark.asyncio
async def test_toggle_automix_followups(cog, interaction):
    view = _MixSettingsView(cog, 123)
    cog._automix_enabled[123] = False
    cog._ensure_automix_state_loaded = AsyncMock()
    await _MixSettingsView.toggle_automix(view, interaction, view.toggle_automix)
    interaction.followup.send.assert_called_with("🎛️ Automix **увімкнено**.", ephemeral=True)
    
    await _MixSettingsView.toggle_automix(view, interaction, view.toggle_automix)
    interaction.followup.send.assert_called_with("🎛️ Automix **вимкнено**.", ephemeral=True)

@pytest.mark.asyncio
async def test_automix_mode_select_error(cog, interaction):
    view = _MixSettingsView(cog, 123)
    select = Mock(values=["invalid"])
    await _MixSettingsView.automix_mode_select(view, interaction, select)
    interaction.response.send_message.assert_called_with("Невідомий режим.", ephemeral=True)

@pytest.mark.asyncio
async def test_fade_select_error(cog, interaction):
    view = _MixSettingsView(cog, 123)
    select = Mock(values=["invalid"])
    await _MixSettingsView.fade_select(view, interaction, select)
    interaction.response.send_message.assert_called_with("Некоректне значення.", ephemeral=True)

@pytest.mark.asyncio
async def test_interaction_check_branches(cog, interaction):
    view = MusicControls(cog, interaction.guild)
    interaction.guild.voice_client = None
    res = await view.interaction_check(interaction)
    assert res is False

@pytest.mark.asyncio
async def test_previous_button_branches(cog, interaction):
    view = MusicControls(cog, interaction.guild)
    cog.processing_buttons.add(123)
    await MusicControls.previous_button(view, interaction, view.previous_button)
    interaction.response.send_message.assert_called_with("Зачекайте, обробляється попередня дія.", ephemeral=True)
    cog.processing_buttons.remove(123)
    
    cog.history_service._history = {}
    cog.repository.get_history.return_value = [{"title": "Old", "url": "U"}]
    cog.history_service.get_last_track.return_value = {"title": "Old", "url": "U"}
    cog.current_song[123] = {"title": "Current"}
    
    with patch('asyncio.sleep', return_value=None):
        await MusicControls.previous_button(view, interaction, view.previous_button)
    assert cog.queue_service.push_front.called

@pytest.mark.asyncio
async def test_control_buttons_errors(cog, interaction):
    view = MusicControls(cog, interaction.guild)
    interaction.guild.voice_client.is_playing.return_value = False
    cog.player_service.is_paused.return_value = False
    await MusicControls.pause_resume_button(view, interaction, view.pause_resume_button)
    interaction.response.send_message.assert_called_with("Зараз нічого не грає.", ephemeral=True)
    
    interaction.guild.voice_client.is_playing.return_value = False
    interaction.guild.voice_client.is_paused.return_value = False
    await MusicControls.skip_button(view, interaction, view.skip_button)
    interaction.response.send_message.assert_called_with("Нічого пропускати.", ephemeral=True)
    
    interaction.guild.voice_client.is_connected.return_value = False
    await MusicControls.leave_button(view, interaction, view.leave_button)
    interaction.response.send_message.assert_called_with("Бот не підключений до голосового каналу.", ephemeral=True)
    
    interaction.guild.voice_client.source = None
    await MusicControls.volume_button(view, interaction, view.volume_button)
    interaction.response.send_message.assert_called_with("Зараз нічого не грає.", ephemeral=True)

@pytest.mark.asyncio
async def test_history_button_complex(cog, interaction):
    view = MusicControls(cog, interaction.guild)
    cog.current_song[123] = {"title": "Now", "duration": 300}
    cog.repository.get_history.return_value = [{"title": "T"*50, "duration": 100} for _ in range(30)]
    await MusicControls.history_button(view, interaction, view.history_button)
    assert interaction.followup.send.called

@pytest.mark.asyncio
async def test_stats_button_error(cog, interaction):
    view = MusicControls(cog, interaction.guild)
    cog._session_tracks[123] = [None]
    await MusicControls.stats_button(view, interaction, view.stats_button)
    interaction.response.send_message.assert_called_with("❌ Помилка отримання статистики.", ephemeral=True)
