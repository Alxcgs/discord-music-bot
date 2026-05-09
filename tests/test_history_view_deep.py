import pytest
import discord
from unittest.mock import Mock, AsyncMock, patch
from discord_music_bot.views.history_view import HistoryView

@pytest.fixture
def interaction():
    i = Mock(spec=discord.Interaction)
    i.guild = Mock()
    i.channel = Mock()
    i.response = Mock()
    i.response.edit_message = AsyncMock()
    i.response.send_message = AsyncMock()
    i.message = Mock()
    i.message.delete = AsyncMock()
    return i

@pytest.fixture
def cog():
    c = Mock()
    c.update_player = AsyncMock()
    c.history_service = Mock()
    return c

@pytest.mark.asyncio
async def test_history_view_bump_player_error(cog, interaction):
    view = HistoryView(cog, 123)
    cog.update_player.side_effect = Exception("Bump error")
    await view._bump_player(interaction)
    cog.update_player.assert_called_once()

@pytest.mark.asyncio
async def test_clear_history_button_error(cog, interaction):
    view = HistoryView(cog, 123)
    cog.history_service.clear_history.side_effect = Exception("Clear error")
    await HistoryView.clear_history_button(view, interaction, view.clear_history_button)
    interaction.response.send_message.assert_called_with("❌ Помилка очищення історії.", ephemeral=True)

@pytest.mark.asyncio
async def test_dismiss_button_error(cog, interaction):
    view = HistoryView(cog, 123)
    interaction.response.edit_message.side_effect = Exception("Edit error")
    await HistoryView.dismiss_button(view, interaction, view.dismiss_button)
    interaction.message.delete.assert_called_once()

@pytest.mark.asyncio
async def test_dismiss_button_total_error(cog, interaction):
    view = HistoryView(cog, 123)
    interaction.response.edit_message.side_effect = Exception("Edit error")
    interaction.message.delete.side_effect = Exception("Delete error")
    await HistoryView.dismiss_button(view, interaction, view.dismiss_button)
