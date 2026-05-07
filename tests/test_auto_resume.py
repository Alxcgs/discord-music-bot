import pytest
from unittest.mock import AsyncMock, Mock, patch, MagicMock
from discord_music_bot.services.auto_resume import auto_resume

@pytest.fixture
def mock_bot():
    bot = Mock()
    bot.get_guild = Mock()
    return bot

@pytest.fixture
def mock_cog():
    cog = AsyncMock()
    cog.repository = AsyncMock()
    cog.queue_service = Mock()
    cog.queue_service.load_from_db = AsyncMock()
    cog.queue_service.push_front = Mock()
    cog.queue_service.get_queue = Mock(return_value=[])
    cog.player_channels = {}
    cog.play_next_song = AsyncMock()
    cog.update_player = AsyncMock()
    return cog

@pytest.mark.asyncio
async def test_auto_resume_no_active_guilds(mock_bot, mock_cog):
    mock_cog.repository.get_all_active_guilds.return_value = []
    
    count = await auto_resume(mock_bot, mock_cog)
    
    assert count == 0
    mock_bot.get_guild.assert_not_called()

@pytest.mark.asyncio
async def test_auto_resume_guild_not_found(mock_bot, mock_cog):
    mock_cog.repository.get_all_active_guilds.return_value = [
        {"guild_id": 1, "voice_channel_id": 10, "text_channel_id": 20, "current_track_url": "http"}
    ]
    mock_bot.get_guild.return_value = None
    
    count = await auto_resume(mock_bot, mock_cog)
    
    assert count == 0
    mock_cog.repository.clear_guild_state.assert_awaited_once_with(1)

@pytest.mark.asyncio
async def test_auto_resume_voice_channel_not_found(mock_bot, mock_cog):
    mock_cog.repository.get_all_active_guilds.return_value = [
        {"guild_id": 1, "voice_channel_id": 10, "text_channel_id": 20, "current_track_url": "http"}
    ]
    mock_guild = Mock()
    mock_guild.get_channel.return_value = None  # Channel not found
    mock_bot.get_guild.return_value = mock_guild
    
    count = await auto_resume(mock_bot, mock_cog)
    
    assert count == 0
    mock_cog.repository.clear_guild_state.assert_awaited_once_with(1)

@pytest.mark.asyncio
async def test_auto_resume_empty_voice_channel(mock_bot, mock_cog):
    mock_cog.repository.get_all_active_guilds.return_value = [
        {"guild_id": 1, "voice_channel_id": 10, "text_channel_id": 20, "current_track_url": "http"}
    ]
    mock_guild = Mock()
    mock_channel = Mock()
    # All members are bots
    bot_member = Mock(bot=True)
    mock_channel.members = [bot_member]
    mock_guild.get_channel.return_value = mock_channel
    mock_bot.get_guild.return_value = mock_guild
    
    count = await auto_resume(mock_bot, mock_cog)
    
    assert count == 0
    mock_cog.repository.clear_guild_state.assert_awaited_once_with(1)

@pytest.mark.asyncio
async def test_auto_resume_success(mock_bot, mock_cog):
    mock_cog.repository.get_all_active_guilds.return_value = [
        {
            "guild_id": 1, 
            "voice_channel_id": 10, 
            "text_channel_id": 20, 
            "current_track_url": "http://test",
            "current_track_title": "Test Title",
            "current_track_duration": 100,
            "current_track_thumbnail": "http://thumb"
        }
    ]
    
    mock_guild = Mock()
    mock_guild.name = "Test Guild"
    
    # Mock text and voice channels properly
    def get_channel_side_effect(channel_id):
        if channel_id == 10:
            mock_vc = AsyncMock()
            mock_vc.name = "Voice Channel"
            human_member = Mock(bot=False)
            mock_vc.members = [human_member]
            mock_vc.connect = AsyncMock(return_value="connected_voice_client")
            return mock_vc
        elif channel_id == 20:
            mock_tc = AsyncMock()
            mock_tc.send = AsyncMock()
            return mock_tc
        return None
        
    mock_guild.get_channel.side_effect = get_channel_side_effect
    mock_bot.get_guild.return_value = mock_guild
    
    # Run the function
    # Mock asyncio.sleep to not wait during tests
    with patch("discord_music_bot.services.auto_resume.asyncio.sleep", new_callable=AsyncMock):
        count = await auto_resume(mock_bot, mock_cog)
    
    assert count == 1
    
    # Verify interactions
    mock_cog.queue_service.load_from_db.assert_awaited_once_with(1)
    mock_cog.queue_service.push_front.assert_called_once()
    args, _ = mock_cog.queue_service.push_front.call_args
    assert args[0] == 1
    assert args[1]["url"] == "http://test"
    assert args[1]["title"] == "Test Title"
    
    assert mock_cog.player_channels[1] == 20
    mock_cog.play_next_song.assert_awaited_once_with(mock_guild, "connected_voice_client")
    mock_cog.update_player.assert_awaited_once()

@pytest.mark.asyncio
async def test_auto_resume_exception_during_connect(mock_bot, mock_cog):
    mock_cog.repository.get_all_active_guilds.return_value = [
        {"guild_id": 1, "voice_channel_id": 10, "text_channel_id": 20, "current_track_url": "http"}
    ]
    
    mock_guild = Mock()
    mock_vc = Mock()
    human_member = Mock(bot=False)
    mock_vc.members = [human_member]
    mock_vc.connect = AsyncMock(side_effect=Exception("Connection Error"))
    
    mock_guild.get_channel.return_value = mock_vc
    mock_bot.get_guild.return_value = mock_guild
    
    count = await auto_resume(mock_bot, mock_cog)
    
    # Should handle exception and clear state
    assert count == 0
    mock_cog.repository.clear_guild_state.assert_awaited_once_with(1)
