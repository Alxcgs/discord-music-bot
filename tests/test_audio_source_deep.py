import pytest
import asyncio
from unittest.mock import Mock, patch
from discord_music_bot.audio_source import YTDLPPipeSource, YTDLSource

class MockProcess:
    def __init__(self, poll_val=None, stdout_data=b''):
        self.poll_val = poll_val
        self.stdout = Mock()
        self.stdout.read.side_effect = self._read_side_effect(stdout_data)
        self.killed = False
    
    def _read_side_effect(self, data):
        # Return data in chunks to simulate pipe behavior
        yield data
        while True:
            yield b''
            
    def poll(self):
        return self.poll_val
    
    def kill(self):
        self.killed = True

@pytest.mark.parametrize("scenario", ["finished", "retries", "padding"])
def test_ytdlp_pipe_source_read_branches(scenario):
    # FRAME_SIZE is 3840
    frame_size = 3840
    
    if scenario == "finished":
        # FFmpeg finished, buffer empty
        ffmpeg = MockProcess(poll_val=0, stdout_data=b'')
        source = YTDLPPipeSource(Mock(), ffmpeg)
        assert source.read() == b''
    
    elif scenario == "padding":
        # FFmpeg finished, buffer has partial data
        ffmpeg = MockProcess(poll_val=0, stdout_data=b'hello')
        source = YTDLPPipeSource(Mock(), ffmpeg)
        # First read will trigger the while loop, get 'hello', then poll() is not None
        frame = source.read()
        assert len(frame) == frame_size
        assert frame.startswith(b'hello')
        assert frame.endswith(b'\x00' * (frame_size - 5))
        # Second read should be empty
        assert source.read() == b''

    elif scenario == "retries":
        # FFmpeg alive, but returning empty chunks
        ffmpeg = Mock()
        ffmpeg.stdout.read.return_value = b''
        ffmpeg.poll.return_value = None # Alive
        source = YTDLPPipeSource(Mock(), ffmpeg)
        source.MAX_READ_RETRIES = 2
        with patch('time.sleep'):
            # Should retry 2 times then return empty if buffer empty
            assert source.read() == b''

def test_ytdlp_pipe_source_cleanup():
    ytdlp = MockProcess(poll_val=None)
    ffmpeg = MockProcess(poll_val=None)
    source = YTDLPPipeSource(ytdlp, ffmpeg)
    source.cleanup()
    assert ytdlp.killed is True
    assert ffmpeg.killed is True

@pytest.mark.asyncio
async def test_ytdl_source_from_track_dict_branches():
    track = {
        'url': 'http://test.com',
        'title': 'Test',
        'duration': 100,
        'thumbnail': 'thumb'
    }
    
    # Test without URL
    res = await YTDLSource.from_track_dict({}, fade_seconds=0)
    assert res is None
    
    # Test with fades
    with patch('discord_music_bot.audio_source.extract_stream_url') as mock_extract, \
         patch('subprocess.Popen') as mock_popen:
        mock_extract.return_value = ('http://stream.url', track)
        mock_p = Mock()
        mock_p.stdout = Mock()
        mock_p.poll.return_value = None
        mock_popen.return_value = mock_p

        res = await YTDLSource.from_track_dict(track, fade_seconds=5, fade_in=True, fade_out=True)
        assert res is not None
        args, kwargs = mock_popen.call_args
        cmd_str = " ".join(args[0])
        assert 'afade=t=in' in cmd_str
        assert 'afade=t=out' in cmd_str

    # Test exception branch
    with patch('discord_music_bot.audio_source.extract_stream_url', side_effect=Exception("extract error")):
        res = await YTDLSource.from_track_dict(track)
        assert res is None
