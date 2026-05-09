import pytest
import asyncio
import subprocess
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from discord_music_bot import audio_source
from discord_music_bot.services import source_service

# --- audio_source.py tests ---
def test_ytdlp_pipe_source_retries():
    ffmpeg = Mock()
    ffmpeg.stdout.read.side_effect = [b'', b'', b'', b'', b'', b'', b'', b'', b'', b'']
    ffmpeg.poll.return_value = None
    ytdlp = Mock()
    source = audio_source.YTDLPPipeSource(ytdlp, ffmpeg)
    with patch('time.sleep'):
        result = source.read()
        assert result == b''

def test_ytdlp_pipe_source_cleanup_failures():
    ffmpeg = Mock()
    ffmpeg.poll.return_value = None
    ffmpeg.kill.side_effect = Exception("Kill Fail")
    ytdlp = Mock()
    ytdlp.poll.return_value = None
    ytdlp.kill.side_effect = Exception("Kill Fail")
    source = audio_source.YTDLPPipeSource(ytdlp, ffmpeg)
    source.cleanup()

@pytest.mark.asyncio
async def test_ytdl_source_from_track_dict_fade_error():
    track = {"url": "http://test", "title": "Test", "duration": 100}
    with patch('subprocess.Popen') as mock_popen:
        mock_popen.return_value = Mock(stdout=Mock())
        await audio_source.YTDLSource.from_track_dict(track, fade_seconds="invalid")

# --- source_service.py tests ---
@pytest.mark.asyncio
async def test_source_service_missing_branches():
    service = source_service.SourceService()
    with patch('yt_dlp.YoutubeDL') as mock_ydl:
        instance = mock_ydl.return_value.__enter__.return_value
        instance.extract_info.side_effect = Exception("Extract Fail")
        
        # Test extract_playlist failure
        assert await service.extract_playlist("http://playlist") == [] # line 21
        # Test get_video_info failure
        assert await service.get_video_info("http://video") is None # line 38
        # Test search_videos failure
        assert await service.search_videos("query") == [] # line 65

@pytest.mark.asyncio
async def test_source_service_extract_playlist_no_entries():
    service = source_service.SourceService()
    with patch('yt_dlp.YoutubeDL') as mock_ydl:
        instance = mock_ydl.return_value.__enter__.return_value
        # Case: _type is not playlist
        instance.extract_info.return_value = {"_type": "video", "url": "test"}
        assert await service.extract_playlist("url") == [] # line 17
        
        # Case: playlist but no entries
        instance.extract_info.return_value = {"_type": "playlist"}
        assert await service.extract_playlist("url") == [] # line 20

@pytest.mark.asyncio
async def test_source_service_extract_playlist_ie_key():
    service = source_service.SourceService()
    with patch('yt_dlp.YoutubeDL') as mock_ydl:
        instance = mock_ydl.return_value.__enter__.return_value
        instance.extract_info.return_value = {"_type": "playlist", "entries": [{"ie_key": "Youtube", "url": "test"}]}
        res = await service.extract_playlist("url")
        assert len(res) == 1
        assert res[0]["url"] == "https://www.youtube.com/watch?v=test" # line 31

@pytest.mark.asyncio
async def test_source_service_get_video_info_ie_key():
    service = source_service.SourceService()
    with patch('yt_dlp.YoutubeDL') as mock_ydl:
        instance = mock_ydl.return_value.__enter__.return_value
        instance.extract_info.return_value = {"ie_key": "Youtube", "url": "test"}
        res = await service.get_video_info("url")
        assert res["url"] == "https://www.youtube.com/watch?v=test" # line 43
