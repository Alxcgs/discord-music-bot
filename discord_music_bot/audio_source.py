import discord
import yt_dlp
import asyncio
import subprocess
import logging
import shlex
from discord_music_bot.config import YDL_OPTIONS, FFMPEG_OPTIONS

class YTDLPPipeSource(discord.AudioSource):
    """Аудіо source що використовує yt-dlp → FFmpeg pipeline."""
    
    FRAME_SIZE = 3840  # 20ms of 48kHz 16-bit stereo PCM
    
    def __init__(self, ytdlp_process, ffmpeg_process):
        self._ytdlp = ytdlp_process
        self._ffmpeg = ffmpeg_process
    
    def read(self):
        data = self._ffmpeg.stdout.read(self.FRAME_SIZE)
        if len(data) < self.FRAME_SIZE:
            return b''
        return data
    
    def cleanup(self):
        try:
            if self._ffmpeg and self._ffmpeg.poll() is None:
                self._ffmpeg.kill()
        except Exception:
            pass
        try:
            if self._ytdlp and self._ytdlp.poll() is None:
                self._ytdlp.kill()
        except Exception:
            pass
    
    def is_opus(self):
        return False


class YTDLSource(discord.PCMVolumeTransformer):
    """Клас для представлення джерела аудіо з yt-dlp."""
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get('title')
        self.url = data.get('webpage_url')
        self.duration = data.get('duration')
        self.thumbnail = data.get('thumbnail')

    @classmethod
    async def from_url(cls, url, *, loop=None, stream=True):
        """Створює екземпляр YTDLSource з URL або пошукового запиту."""
        loop = loop or asyncio.get_event_loop()
        logging.info(f"Attempting to extract info for URL: {url}")

        try:
            ydl_opts = YDL_OPTIONS.copy()
            
            if not url.startswith('http'):
                url = f"ytsearch:{url}"

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                try:
                    data = await loop.run_in_executor(None, lambda: ydl.extract_info(url, download=False))
                except Exception as e:
                    logging.error(f"Failed to extract info: {e}")
                    return None

            if data is None: return None
            if 'entries' in data: data = data['entries'][0]

            webpage_url = data.get('webpage_url') or data.get('url') or url
            logging.info(f"Creating audio pipeline for: {data.get('title')}")
            
            # Розбираємо глобальні FFMPEG опції для використання в subprocess
            # FFMPEG_OPTIONS['options'] містить рядок параметрів, треба его розбити на list
            ffmpeg_opts_list = shlex.split(FFMPEG_OPTIONS['options'])
            
            # yt-dlp → pipe → FFmpeg
            ytdlp_process = subprocess.Popen(
                [
                    'yt-dlp',
                    '--format', ydl_opts['format'], # Використовуємо формат з конфігу (opus HQ)
                    '--output', '-',
                    '--quiet', '--no-warnings', '--no-playlist',
                    webpage_url
                ],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
            )
            
            ffmpeg_cmd = [
                'ffmpeg',
                '-i', 'pipe:0',
                '-f', 's16le',
            ] + ffmpeg_opts_list + ['pipe:1'] # Додаємо опції з config.py (aresample, rate, etc)
            
            ffmpeg_process = subprocess.Popen(
                ffmpeg_cmd,
                stdin=ytdlp_process.stdout,
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                bufsize=1024*1024
            )
            
            ytdlp_process.stdout.close()
            
            source = YTDLPPipeSource(ytdlp_process, ffmpeg_process)
            logging.info(f"Audio pipeline started for: {data.get('title')}")
            return cls(source, data=data)

        except Exception as e:
            logging.error(f"Error in from_url: {str(e)}", exc_info=True)
            return None