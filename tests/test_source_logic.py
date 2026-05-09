import pytest
import yt_dlp
from unittest.mock import MagicMock, patch
from discord_music_bot.services.source_service import SourceService

@pytest.fixture
def source_service():
    return SourceService()

@pytest.mark.asyncio
async def test_get_video_info_success(source_service):
    mock_info = {
        'title': 'Test Video',
        'webpage_url': 'https://youtube.com/watch?v=123',
        'duration': 180,
        'thumbnail': 'https://img.com/123.jpg'
    }
    
    with patch('yt_dlp.YoutubeDL') as mock_ytdl:
        instance = mock_ytdl.return_value.__enter__.return_value
        instance.extract_info.return_value = mock_info
        
        res = await source_service.get_video_info('https://youtube.com/watch?v=123')
        
        assert res['title'] == 'Test Video'
        assert res['duration'] == 180

@pytest.mark.asyncio
async def test_get_video_info_search(source_service):
    mock_info = {
        'entries': [{
            'title': 'Search Result',
            'webpage_url': 'https://youtube.com/watch?v=search',
            'duration': 200
        }]
    }
    
    with patch('yt_dlp.YoutubeDL') as mock_ytdl:
        instance = mock_ytdl.return_value.__enter__.return_value
        instance.extract_info.return_value = mock_info
        
        res = await source_service.get_video_info('search query')
        assert res['title'] == 'Search Result'

@pytest.mark.asyncio
async def test_search_videos(source_service):
    mock_info = {
        'entries': [
            {'title': 'R1', 'webpage_url': 'u1', 'duration': 60},
            {'title': 'R2', 'webpage_url': 'u2', 'duration': 120}
        ]
    }
    
    with patch('yt_dlp.YoutubeDL') as mock_ytdl:
        instance = mock_ytdl.return_value.__enter__.return_value
        instance.extract_info.return_value = mock_info
        
        results = await source_service.search_videos('query', max_results=2)
        assert len(results) == 2
        assert results[0]['title'] == 'R1'

@pytest.mark.asyncio
async def test_extract_playlist(source_service):
    mock_info = {
        'title': 'My Playlist',
        'entries': [
            {'title': 'P1', 'url': 'pu1', 'duration': 10},
            {'title': 'P2', 'url': 'pu2', 'duration': 20}
        ]
    }
    
    with patch('yt_dlp.YoutubeDL') as mock_ytdl:
        instance = mock_ytdl.return_value.__enter__.return_value
        instance.extract_info.return_value = mock_info
        
        title, tracks = await source_service.extract_playlist('https://playlist.com')
        assert title == 'My Playlist'
        assert len(tracks) == 2
        assert tracks[0]['title'] == 'P1'

@pytest.mark.asyncio
async def test_source_service_errors(source_service):
    with patch('yt_dlp.YoutubeDL') as mock_ytdl:
        instance = mock_ytdl.return_value.__enter__.return_value
        instance.extract_info.side_effect = Exception("YTDL Error")
        
        assert await source_service.get_video_info('url') is None
        assert await source_service.search_videos('query') == []
        title, tracks = await source_service.extract_playlist('url')
        assert title is None
        assert tracks == []
