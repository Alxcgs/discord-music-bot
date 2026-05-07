import pytest
from unittest.mock import patch, MagicMock
from discord_music_bot.services.source_service import SourceService

@pytest.fixture
def source_service():
    return SourceService()

@pytest.mark.asyncio
async def test_get_video_info_success(source_service):
    with patch("discord_music_bot.services.source_service.yt_dlp.YoutubeDL") as mock_ytdl:
        mock_instance = mock_ytdl.return_value.__enter__.return_value
        mock_instance.extract_info.return_value = {
            "title": "Test Title",
            "webpage_url": "http://test",
            "duration": 120,
            "thumbnail": "http://thumb"
        }
        
        info = await source_service.get_video_info("http://test")
        
        assert info is not None
        assert info["title"] == "Test Title"
        assert info["url"] == "http://test"
        assert info["duration"] == 120

@pytest.mark.asyncio
async def test_get_video_info_search(source_service):
    with patch("discord_music_bot.services.source_service.yt_dlp.YoutubeDL") as mock_ytdl:
        mock_instance = mock_ytdl.return_value.__enter__.return_value
        mock_instance.extract_info.return_value = {
            "entries": [{
                "title": "Search Result",
                "webpage_url": "http://search",
                "duration": 200,
                "thumbnail": "http://thumb2"
            }]
        }
        
        info = await source_service.get_video_info("search query")
        
        assert info is not None
        assert info["title"] == "Search Result"
        assert info["url"] == "http://search"
        mock_instance.extract_info.assert_called_once_with("ytsearch:search query", download=False)

@pytest.mark.asyncio
async def test_search_videos(source_service):
    with patch("discord_music_bot.services.source_service.yt_dlp.YoutubeDL") as mock_ytdl:
        mock_instance = mock_ytdl.return_value.__enter__.return_value
        mock_instance.extract_info.return_value = {
            "entries": [
                {"title": "Res 1", "webpage_url": "http://res1", "duration": 10},
                {"title": "Res 2", "webpage_url": "http://res2", "duration": 20}
            ]
        }
        
        results = await source_service.search_videos("query", max_results=2)
        
        assert len(results) == 2
        assert results[0]["title"] == "Res 1"
        assert results[1]["title"] == "Res 2"
        mock_instance.extract_info.assert_called_once_with("ytsearch2:query", download=False)

@pytest.mark.asyncio
async def test_extract_playlist(source_service):
    with patch("discord_music_bot.services.source_service.yt_dlp.YoutubeDL") as mock_ytdl:
        mock_instance = mock_ytdl.return_value.__enter__.return_value
        mock_instance.extract_info.return_value = {
            "title": "My Playlist",
            "entries": [
                {"title": "Track 1", "url": "http://track1", "duration": 100},
                {"title": "Track 2", "url": "track2_id", "duration": 200}
            ]
        }
        
        title, tracks = await source_service.extract_playlist("http://playlist")
        
        assert title == "My Playlist"
        assert len(tracks) == 2
        assert tracks[0]["title"] == "Track 1"
        assert tracks[0]["url"] == "http://track1"
        assert tracks[1]["title"] == "Track 2"
        assert tracks[1]["url"] == "https://www.youtube.com/watch?v=track2_id"
