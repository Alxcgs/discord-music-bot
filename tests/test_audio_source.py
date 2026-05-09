import pytest
import discord
from unittest.mock import MagicMock, patch
from discord_music_bot.audio_source import YTDLPPipeSource, YTDLSource

@pytest.fixture
def mock_processes():
    ytdlp = MagicMock()
    ytdlp.poll.return_value = None # Still running
    ffmpeg = MagicMock()
    ffmpeg.stdout.read.return_value = b'\x01' * 3840 # One full frame
    ffmpeg.poll.return_value = None # Still running
    return ytdlp, ffmpeg

def test_ytdlp_pipe_source_read(mock_processes):
    ytdlp, ffmpeg = mock_processes
    source = YTDLPPipeSource(ytdlp, ffmpeg)
    
    # Test reading a full frame
    frame = source.read()
    assert len(frame) == 3840
    ffmpeg.stdout.read.assert_called_with(3840)

def test_ytdlp_pipe_source_end_of_track(mock_processes):
    ytdlp, ffmpeg = mock_processes
    source = YTDLPPipeSource(ytdlp, ffmpeg)
    
    # Mock FFmpeg ending
    ffmpeg.stdout.read.return_value = b''
    ffmpeg.poll.return_value = 0
    
    frame = source.read()
    assert frame == b''

def test_ytdlp_pipe_source_cleanup(mock_processes):
    ytdlp, ffmpeg = mock_processes
    source = YTDLPPipeSource(ytdlp, ffmpeg)
    
    source.cleanup()
    ffmpeg.kill.assert_called()
    ytdlp.kill.assert_called()

def test_ytdl_source_properties():
    mock_source = MagicMock(spec=discord.AudioSource)
    mock_source.is_opus.return_value = False
    data = {
        'title': 'T',
        'webpage_url': 'U',
        'duration': 100,
        'thumbnail': 'TH'
    }
    source = YTDLSource(mock_source, data=data)
    assert source.title == 'T'
    assert source.url == 'U'
    assert source.duration == 100
    assert source.thumbnail == 'TH'
    assert source.is_opus() is False

@pytest.mark.asyncio
async def test_ytdl_source_from_track_dict_no_url():
    res = await YTDLSource.from_track_dict({})
    assert res is None

@pytest.mark.asyncio
async def test_ytdl_source_from_track_dict_success():
    track = {'url': 'http://test.com', 'title': 'Test'}
    
    with patch('subprocess.Popen') as mock_popen:
        mock_proc = MagicMock()
        mock_popen.return_value = mock_proc
        
        # We need to mock the YTDLPPipeSource creation too if we want to avoid real FFmpeg
        res = await YTDLSource.from_track_dict(track)
        assert res is not None
        assert res.title == 'Test'
