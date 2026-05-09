import pytest
import os
import signal
import subprocess
from unittest.mock import Mock, patch, MagicMock
from discord_music_bot.healthcheck import _kill_zombie_processes, cleanup_zombie_processes, start_zombie_cleanup
import asyncio

@pytest.mark.parametrize("os_name", ["nt", "posix"])
def test_kill_zombie_processes_branches(os_name):
    with patch('os.name', os_name):
        if os_name == "nt":
            # Mock tasklist output
            stdout = '"yt-dlp.exe","1234","Console","1","10,000 K"\n"ffmpeg.exe","5678","Console","1","20,000 K"'
            with patch('subprocess.run') as mock_run:
                mock_run.side_effect = [
                    Mock(stdout=stdout), # tasklist
                    Mock(), # taskkill 1
                    Mock(), # taskkill 2
                ]
                with patch('os.getpid', return_value=9999):
                    killed = _kill_zombie_processes()
                    assert killed == 2
                    
            # Test failure branch
            with patch('subprocess.run', side_effect=Exception("Error")):
                assert _kill_zombie_processes() == 0
        else:
            # Linux/macOS
            stdout = '1234 1 Z yt-dlp\n5678 1 S ffmpeg'
            with patch('subprocess.run') as mock_run:
                mock_run.return_value = Mock(stdout=stdout)
                with patch('os.kill') as mock_kill:
                    killed = _kill_zombie_processes()
                    assert killed == 2 # Both 1234 (Z) and 5678 (ppid=1)
                    
            # Test failure branch
            with patch('subprocess.run', side_effect=Exception("Error")):
                assert _kill_zombie_processes() == 0

@pytest.mark.asyncio
async def test_cleanup_zombie_processes_loop():
    with patch('discord_music_bot.healthcheck._kill_zombie_processes', return_value=1) as mock_kill:
        # We want to test the loop but break it quickly
        task = asyncio.create_task(cleanup_zombie_processes(interval_seconds=0.1))
        await asyncio.sleep(0.2)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        mock_kill.assert_called()

def test_start_zombie_cleanup():
    loop = Mock()
    start_zombie_cleanup(loop, 100)
    loop.create_task.assert_called()
