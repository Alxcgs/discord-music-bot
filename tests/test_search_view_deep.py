import pytest
import discord
from unittest.mock import Mock, AsyncMock, MagicMock
from discord_music_bot.views.search_results_view import SearchResultsView
from discord_music_bot import consts

@pytest.fixture
def view():
    cog = Mock()
    user = Mock(id=111)
    results = [{"title": f"Track {i}", "duration": 100} for i in range(15)]
    return SearchResultsView(cog, user, results)

@pytest.mark.asyncio
async def test_search_view_user_check_fail(view):
    interaction = MagicMock()
    interaction.user.id = 222 # Different user
    interaction.response.send_message = AsyncMock()
    
    # Callback check
    callback = view.create_select_callback(0)
    await callback(interaction)
    interaction.response.send_message.assert_called_with("Ви не можете використовувати це меню.", ephemeral=True) # line 46

@pytest.mark.asyncio
async def test_search_view_navigation(view):
    interaction = MagicMock()
    interaction.user = view.user
    interaction.response.edit_message = AsyncMock()
    
    # Next page
    await view.next_page(interaction)
    assert view.current_page == 1
    
    # Prev page success
    await view.prev_page(interaction)
    assert view.current_page == 0 # line 55
    
    # Prev page wrong user
    interaction.user = Mock(id=222)
    await view.prev_page(interaction)
    assert view.current_page == 0 # line 54 (returns early)
