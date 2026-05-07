import asyncio
import pytest
from unittest.mock import Mock, patch, AsyncMock
import discord
from discord_music_bot.services.player_service import PlayerService

@pytest.fixture
def player_service():
    return PlayerService()

@pytest.fixture
def mock_vc():
    vc = Mock(spec=discord.VoiceClient)
    vc.is_connected.return_value = True
    vc.is_playing.return_value = False
    vc.is_paused.return_value = False
    return vc

def test_pause(player_service, mock_vc):
    mock_vc.is_playing.return_value = True
    player_service.pause(mock_vc)
    mock_vc.pause.assert_called_once()
    
    mock_vc.is_playing.return_value = False
    mock_vc.pause.reset_mock()
    player_service.pause(mock_vc)
    mock_vc.pause.assert_not_called()

def test_resume(player_service, mock_vc):
    mock_vc.is_paused.return_value = True
    player_service.resume(mock_vc)
    mock_vc.resume.assert_called_once()

    mock_vc.is_paused.return_value = False
    mock_vc.resume.reset_mock()
    player_service.resume(mock_vc)
    mock_vc.resume.assert_not_called()

def test_stop(player_service, mock_vc):
    mock_vc.is_playing.return_value = True
    player_service.stop(mock_vc)
    mock_vc.stop.assert_called_once()

def test_is_playing_and_paused(player_service, mock_vc):
    mock_vc.is_playing.return_value = True
    assert player_service.is_playing(mock_vc) is True
    
    mock_vc.is_paused.return_value = True
    assert player_service.is_paused(mock_vc) is True

@pytest.mark.asyncio
async def test_play_stream_success(player_service, mock_vc):
    loop = asyncio.get_running_loop()
    def after_callback(e): pass
    
    mock_player = Mock()
    track_dict = {"url": "http://test", "title": "Test Track"}
    
    with patch("discord_music_bot.services.player_service.YTDLSource.from_track_dict", new_callable=AsyncMock) as mock_from_track:
        mock_from_track.return_value = mock_player
        
        result = await player_service.play_stream(mock_vc, track_dict, loop, after_callback)
        
        assert result == mock_player
        mock_from_track.assert_awaited_once_with(track_dict, loop=loop, fade_seconds=0.0, fade_in=False, fade_out=False)
        mock_vc.play.assert_called_once_with(mock_player, after=after_callback)

@pytest.mark.asyncio
async def test_play_stream_not_connected(player_service, mock_vc):
    loop = asyncio.get_running_loop()
    mock_vc.is_connected.return_value = False
    track_dict = {"url": "http://test", "title": "Test Track"}
    
    with pytest.raises(discord.errors.ClientException, match="Voice client is not connected"):
        await player_service.play_stream(mock_vc, track_dict, loop, lambda e: None)

@pytest.mark.asyncio
async def test_play_stream_source_creation_failed(player_service, mock_vc):
    loop = asyncio.get_running_loop()
    track_dict = {"url": "http://test", "title": "Test Track"}
    
    with patch("discord_music_bot.services.player_service.YTDLSource.from_track_dict", new_callable=AsyncMock) as mock_from_track:
        mock_from_track.return_value = None
        
        with pytest.raises(ValueError, match="Failed to create audio source"):
            await player_service.play_stream(mock_vc, track_dict, loop, lambda e: None)

@pytest.mark.asyncio
async def test_play_stream_connection_lost_during_extraction(player_service, mock_vc):
    loop = asyncio.get_running_loop()
    track_dict = {"url": "http://test", "title": "Test Track"}
    
    async def mock_extract(*args, **kwargs):
        # Simulate connection dropping while waiting for yt-dlp
        mock_vc.is_connected.return_value = False
        return Mock()

    with patch("discord_music_bot.services.player_service.YTDLSource.from_track_dict", new=mock_extract):
        with pytest.raises(discord.errors.ClientException, match="Voice connection lost"):
            await player_service.play_stream(mock_vc, track_dict, loop, lambda e: None)
