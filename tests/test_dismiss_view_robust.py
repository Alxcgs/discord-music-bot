import pytest
import discord
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from discord_music_bot.views.dismiss_view import DismissView

class MockInteraction(Mock):
    def __init__(self, *args, **kwargs):
        super().__init__(spec=discord.Interaction, *args, **kwargs)
        self.response = AsyncMock(spec=discord.InteractionResponse)
        self.message = MagicMock(spec=discord.Message)
        self.user = MagicMock(spec=discord.Member)
        self.guild = MagicMock(spec=discord.Guild)

@pytest.mark.asyncio
async def test_dismiss_view_fixed():
    view = DismissView()
    i = MockInteraction()
    
    # Branch 1: Success
    await DismissView.dismiss_button(view, i, view.dismiss_button)
    i.response.edit_message.assert_called()

    # Branch 2: Edit Fail, Delete Success
    i.response.edit_message.side_effect = Exception("Fail")
    await DismissView.dismiss_button(view, i, view.dismiss_button)
    i.message.delete.assert_called()

    # Branch 3: Both Fail
    i.message.delete.side_effect = Exception("Fail")
    await DismissView.dismiss_button(view, i, view.dismiss_button)
