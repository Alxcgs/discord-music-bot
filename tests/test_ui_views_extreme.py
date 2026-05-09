import pytest
import discord
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from discord_music_bot.views.music_controls import MusicControls, VolumeModal, _MixSettingsView
from discord_music_bot.views.dismiss_view import DismissView
from discord_music_bot import consts
import asyncio

# A better interaction mock that avoids common TypeErrors in discord.py
def create_robust_interaction():
    i = MagicMock(spec=discord.Interaction)
    # discord.py often checks i.guild, i.user, i.channel
    i.guild = MagicMock(spec=discord.Guild)
    i.guild.id = 123
    i.guild_id = 123
    i.user = MagicMock(spec=discord.Member)
    i.user.id = 111
    i.channel = MagicMock(spec=discord.TextChannel)
    i.channel.id = 456
    i.response = MagicMock(spec=discord.InteractionResponse)
    i.response.send_message = AsyncMock()
    i.response.edit_message = AsyncMock()
    i.followup = MagicMock(spec=discord.Webhook)
    i.followup.send = AsyncMock()
    i.message = MagicMock(spec=discord.Message)
    i.message.delete = AsyncMock()
    return i

@pytest.fixture
def cog():
    c = Mock()
    c._automix_enabled = {}
    c._automix_strategy_mode = {}
    c._fade_seconds = {}
    c._dj_settings_cache = {123: {"enabled": True, "persona": "chill"}}
    c._automix_settings_cache = {}
    c.queue_service = Mock()
    c.queue_service.get_queue.return_value = []
    c.update_player = AsyncMock()
    c._ensure_dj_state_loaded = AsyncMock()
    c.repository = AsyncMock()
    return c

@pytest.mark.asyncio
async def test_volume_modal_no_playing(cog):
    modal = VolumeModal(cog, 123)
    i = create_robust_interaction()
    i.guild.voice_client = None
    await modal.on_submit(i)
    i.response.send_message.assert_called_with("Зараз нічого не грає.", ephemeral=True)

@pytest.mark.asyncio
async def test_mix_settings_view_toggles(cog):
    view = _MixSettingsView(cog, 123)
    i = create_robust_interaction()
    button = MagicMock(spec=discord.ui.Button)
    
    # Toggle DJ
    await view.toggle_dj(i, button)
    i.followup.send.assert_called()

@pytest.mark.asyncio
async def test_dismiss_view_full_coverage():
    view = DismissView()
    i = create_robust_interaction()
    
    # Case 1: Success
    await view.dismiss_button(i, Mock())
    i.response.edit_message.assert_called()
    
    # Case 2: Edit fail, delete success
    i.response.edit_message.side_effect = Exception("Fail")
    await view.dismiss_button(i, Mock())
    i.message.delete.assert_called()
    
    # Case 3: Both fail
    i.message.delete.side_effect = Exception("Fail")
    await view.dismiss_button(i, Mock())
