import pytest
import discord
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from discord_music_bot.views.queue_view import QueueView, MoveTrackModal
from discord_music_bot import consts

@pytest.fixture
def interaction():
    i = Mock(spec=discord.Interaction)
    i.guild = Mock()
    i.guild.id = 123
    i.channel = Mock()
    i.response = Mock()
    i.response.edit_message = AsyncMock()
    i.response.send_message = AsyncMock()
    i.response.send_modal = AsyncMock()
    i.message = Mock()
    i.message.delete = AsyncMock()
    return i

@pytest.fixture
def cog():
    c = Mock()
    c.update_player = AsyncMock()
    c.queue_service = Mock()
    c.queue_service.get_queue.return_value = []
    c.current_song = {}
    return c

@pytest.mark.asyncio
async def test_move_track_modal_branches(cog, interaction):
    qv = QueueView(cog, interaction.guild)
    modal = MoveTrackModal(qv)
    
    # ValueError branch
    modal.from_pos = Mock(value="abc")
    await modal.on_submit(interaction)
    interaction.response.send_message.assert_called_with("❗ Введіть числа.", ephemeral=True)
    
    # Range check branch
    modal.from_pos.value = "5"
    modal.to_pos = Mock(value="1")
    cog.queue_service.get_queue.return_value = [1, 2]
    await modal.on_submit(interaction)
    interaction.response.send_message.assert_called_with("❗ Некоректні позиції. Допустимий діапазон: **1–2**.", ephemeral=True)
    
    # Same position branch
    modal.from_pos.value = "1"
    modal.to_pos.value = "1"
    cog.queue_service.get_queue.return_value = [1, 2]
    await modal.on_submit(interaction)
    interaction.response.send_message.assert_called_with("Трек вже на цій позиції.", ephemeral=True)
    
    # Move error branch
    modal.from_pos.value = "1"
    modal.to_pos.value = "2"
    cog.queue_service.move_track.return_value = None
    await modal.on_submit(interaction)
    interaction.response.send_message.assert_called_with("❗ Помилка переміщення.", ephemeral=True)

@pytest.mark.asyncio
async def test_queue_view_chunks(cog, interaction):
    tracks = [{"title": "T" * 100, "url": "U", "duration": 60} for _ in range(20)]
    cog.queue_service.get_queue.return_value = tracks
    qv = QueueView(cog, interaction.guild)
    embed = qv.create_embed()
    fields = [f for f in embed.fields if f.name == "📑 Треки в черзі" or f.name == "\u200b"]
    assert len(fields) > 0

@pytest.mark.asyncio
async def test_queue_view_bump_error(cog, interaction):
    qv = QueueView(cog, interaction.guild)
    cog.update_player.side_effect = Exception("Bump error")
    await qv._bump_player(interaction)

@pytest.mark.asyncio
async def test_queue_view_shuffle_error(cog, interaction):
    cog.queue_service.get_queue.return_value = [1]
    qv = QueueView(cog, interaction.guild)
    await qv.shuffle_queue(interaction)
    interaction.response.send_message.assert_called_with("Недостатньо треків для перемішування.", ephemeral=True)

@pytest.mark.asyncio
async def test_queue_view_close_error(cog, interaction):
    qv = QueueView(cog, interaction.guild)
    interaction.response.edit_message.side_effect = Exception("Edit error")
    await qv.close_view(interaction)
    interaction.message.delete.assert_called_once()

@pytest.mark.asyncio
async def test_queue_view_close_total_error(cog, interaction):
    qv = QueueView(cog, interaction.guild)
    interaction.response.edit_message.side_effect = Exception("Edit error")
    interaction.message.delete.side_effect = Exception("Delete error")
    await qv.close_view(interaction)
