import pytest
import discord
from unittest.mock import Mock, AsyncMock, patch
from discord_music_bot.views.queue_view import QueueView, MoveTrackModal
from discord_music_bot.views.history_view import HistoryView
from discord_music_bot.views.search_results_view import SearchResultsView
from discord_music_bot.views.dismiss_view import DismissView
from discord_music_bot import consts

@pytest.fixture
def mock_cog():
    cog = Mock()
    cog.queue_service = Mock()
    cog.queue_service.get_queue = Mock(return_value=[{"title": f"Track {i}", "url": f"url{i}", "duration": 100} for i in range(25)])
    cog.queue_service.move_track = Mock(return_value={"title": "Moved Track"})
    cog.repository = AsyncMock()
    cog.current_song = {123: {"title": "Playing", "url": "urlp", "duration": 300, "requester": Mock(mention="@user")}}
    cog.update_player = AsyncMock()
    return cog

@pytest.fixture
def mock_interaction():
    interaction = Mock(spec=discord.Interaction)
    interaction.guild.id = 123
    interaction.user.id = 111
    interaction.user.mention = "@user"
    interaction.response = Mock()
    interaction.response.send_message = AsyncMock()
    interaction.response.edit_message = AsyncMock()
    interaction.response.send_modal = AsyncMock()
    interaction.response.defer = AsyncMock()
    interaction.followup = Mock()
    interaction.followup.send = AsyncMock()
    interaction.message = Mock()
    interaction.message.delete = AsyncMock()
    return interaction

@pytest.mark.asyncio
async def test_queue_view_full(mock_cog, mock_interaction):
    guild = Mock()
    guild.id = 123
    view = QueueView(mock_cog, guild)
    await view.next_page(mock_interaction)
    await view.shuffle_queue(mock_interaction)
    await view.clear_queue(mock_interaction)
    await view.close_view(mock_interaction)
    modal = MoveTrackModal(view)
    modal.from_pos = Mock(value="2")
    modal.to_pos = Mock(value="1")
    await modal.on_submit(mock_interaction)

@pytest.mark.asyncio
async def test_history_view_full(mock_cog, mock_interaction):
    mock_cog.history_service = Mock()
    view = HistoryView(mock_cog, 123)
    # Use the original function from the class
    await HistoryView.clear_history_button(view, mock_interaction, view.clear_history_button)
    await HistoryView.dismiss_button(view, mock_interaction, view.dismiss_button)

@pytest.mark.asyncio
async def test_search_results_view_full(mock_cog, mock_interaction):
    results = [{"title": f"Res {i}", "url": f"url{i}", "duration": 100} for i in range(25)]
    view = SearchResultsView(mock_cog, mock_interaction.user, results)
    await view.next_page(mock_interaction)
    await view.cancel(mock_interaction)
    callback = view.create_select_callback(2)
    await callback(mock_interaction)

@pytest.mark.asyncio
async def test_dismiss_view(mock_interaction):
    view = DismissView()
    await DismissView.dismiss_button(view, mock_interaction, view.dismiss_button)
