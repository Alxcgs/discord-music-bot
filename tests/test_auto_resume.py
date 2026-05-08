import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone, timedelta
from discord_music_bot.services.auto_resume import auto_resume
from discord_music_bot import consts

@pytest.fixture
def mock_bot():
    bot = MagicMock()
    return bot

@pytest.fixture
def mock_cog():
    cog = MagicMock()
    cog.repository = AsyncMock()
    cog.queue_service = MagicMock() # Use MagicMock for synchronous methods
    cog.queue_service.get_queue = MagicMock(return_value=[])
    cog.queue_service.load_from_db = AsyncMock()
    cog.queue_service.push_front = MagicMock()
    cog.player_channels = {}
    cog.play_next_song = AsyncMock()
    cog.update_player = AsyncMock()
    return cog

@pytest.mark.asyncio
async def test_auto_resume_no_active_guilds(mock_bot, mock_cog):
    mock_cog.repository.get_all_active_guilds.return_value = []
    
    count = await auto_resume(mock_bot, mock_cog)
    
    assert count == 0
    mock_cog.repository.get_all_active_guilds.assert_called_once()

@pytest.mark.asyncio
async def test_auto_resume_staleness_policy(mock_bot, mock_cog):
    # Сесія створена 25 годин тому
    stale_time = (datetime.now(timezone.utc) - timedelta(hours=25)).strftime("%Y-%m-%d %H:%M:%S")
    
    mock_cog.repository.get_all_active_guilds.return_value = [
        {
            'guild_id': 123,
            'updated_at': stale_time,
            'voice_channel_id': 456,
            'text_channel_id': 789,
            'current_track_url': 'http://example.com',
        }
    ]
    
    count = await auto_resume(mock_bot, mock_cog)
    
    assert count == 0
    # Перевірка що стан було очищено через застарілість
    mock_cog.repository.clear_guild_state.assert_called_with(123)

@pytest.mark.asyncio
async def test_auto_resume_missing_guild(mock_bot, mock_cog):
    valid_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    mock_cog.repository.get_all_active_guilds.return_value = [
        {
            'guild_id': 123,
            'updated_at': valid_time,
            'voice_channel_id': 456,
            'text_channel_id': 789,
            'current_track_url': 'http://example.com',
        }
    ]
    
    mock_bot.get_guild.return_value = None # Guild не знайдено
    
    count = await auto_resume(mock_bot, mock_cog)
    
    assert count == 0
    mock_cog.repository.clear_guild_state.assert_called_with(123)

@pytest.mark.asyncio
async def test_auto_resume_empty_channel(mock_bot, mock_cog):
    valid_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    mock_cog.repository.get_all_active_guilds.return_value = [
        {
            'guild_id': 123,
            'updated_at': valid_time,
            'voice_channel_id': 456,
            'text_channel_id': 789,
            'current_track_url': 'http://example.com',
        }
    ]
    
    mock_guild = MagicMock()
    mock_voice_channel = MagicMock()
    # Тільки боти в каналі
    mock_member = MagicMock()
    mock_member.bot = True
    mock_voice_channel.members = [mock_member]
    
    mock_bot.get_guild.return_value = mock_guild
    mock_guild.get_channel.return_value = mock_voice_channel
    
    count = await auto_resume(mock_bot, mock_cog)
    
    assert count == 0
    mock_cog.repository.clear_guild_state.assert_called_with(123)

@pytest.mark.asyncio
async def test_auto_resume_success(mock_bot, mock_cog):
    valid_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    mock_cog.repository.get_all_active_guilds.return_value = [
        {
            'guild_id': 123,
            'updated_at': valid_time,
            'voice_channel_id': 456,
            'text_channel_id': 789,
            'current_track_url': 'http://example.com',
            'current_track_title': 'Test Track'
        }
    ]
    
    mock_guild = MagicMock()
    mock_voice_channel = MagicMock()
    mock_voice_channel.connect = AsyncMock()
    
    # Є людина в каналі
    mock_human = MagicMock()
    mock_human.bot = False
    mock_voice_channel.members = [mock_human]
    
    mock_bot.get_guild.return_value = mock_guild
    mock_guild.get_channel.return_value = mock_voice_channel
    
    # Мокаємо відправку повідомлення в текстовий канал
    mock_text_channel = AsyncMock()
    mock_guild.get_channel.side_effect = lambda id: mock_voice_channel if id == 456 else mock_text_channel
    
    count = await auto_resume(mock_bot, mock_cog)
    
    assert count == 1
    mock_voice_channel.connect.assert_called_once()
    mock_cog.queue_service.load_from_db.assert_called_with(123)
    mock_cog.queue_service.push_front.assert_called_once()
    mock_cog.play_next_song.assert_called_once()
    mock_text_channel.send.assert_called()
