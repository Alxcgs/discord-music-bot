import discord
import yt_dlp
import asyncio
import subprocess
import logging
import shlex
import time
from discord_music_bot.config import YDL_OPTIONS, FFMPEG_OPTIONS

class YTDLPPipeSource(discord.AudioSource):
    """Аудіо source що використовує yt-dlp → FFmpeg pipeline.
    Буферизує дані щоб уникнути передчасного закінчення треку
    при тимчасових затримках в pipe."""
    
    FRAME_SIZE = 3840  # 20ms of 48kHz 16-bit stereo PCM
    MAX_READ_RETRIES = 10  # Кількість повторних спроб читання при неповному буфері (~1с толерантність)
    
    def __init__(self, ytdlp_process, ffmpeg_process):
        self._ytdlp = ytdlp_process
        self._ffmpeg = ffmpeg_process
        self._buffer = b''
    
    def read(self):
        # Зчитуємо з pipe поки не наберемо повний фрейм
        retries = 0
        while len(self._buffer) < self.FRAME_SIZE:
            chunk = self._ffmpeg.stdout.read(self.FRAME_SIZE - len(self._buffer))
            if chunk:
                self._buffer += chunk
                retries = 0  # Скидаємо лічильник при успішному читанні
            else:
                # Порожнє читання — перевіряємо чи FFmpeg ще працює
                if self._ffmpeg.poll() is not None:
                    # FFmpeg завершився — віддаємо залишок буфера (з padding тишею)
                    if self._buffer:
                        frame = self._buffer.ljust(self.FRAME_SIZE, b'\x00')
                        self._buffer = b''
                        return frame
                    return b''  # Справжній кінець трека
                
                # FFmpeg ще працює, але pipe тимчасово порожній (мережева затримка)
                retries += 1
                if retries >= self.MAX_READ_RETRIES:
                    # Занадто багато порожніх читань — мабуть справді кінець
                    if self._buffer:
                        frame = self._buffer.ljust(self.FRAME_SIZE, b'\x00')
                        self._buffer = b''
                        return frame
                    return b''
                time.sleep(0.1)  # Пауза перед повторною спробою (100ms)
        
        # Витягуємо рівно один фрейм з буфера
        frame = self._buffer[:self.FRAME_SIZE]
        self._buffer = self._buffer[self.FRAME_SIZE:]
        return frame
    
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
    async def from_track_dict(
        cls,
        track_dict: dict,
        *,
        loop=None,
        fade_seconds: float = 0.0,
        fade_in: bool = False,
        fade_out: bool = False,
    ):
        """Створює екземпляр YTDLSource напряму з метаданих треку (без повторного виклику yt-dlp API)."""
        loop = loop or asyncio.get_event_loop()
        
        url = track_dict.get('webpage_url') or track_dict.get('url')
        if not url:
            logging.error("No URL provided in track_dict")
            return None

        logging.info(f"Creating audio pipeline for: {track_dict.get('title', 'Unknown')}")

        try:
            ydl_opts = YDL_OPTIONS.copy()
            
            # Розбираємо глобальні FFMPEG опції для використання в subprocess
            # FFMPEG_OPTIONS['options'] містить рядок параметрів, треба його розбити на list
            ffmpeg_opts_list = shlex.split(FFMPEG_OPTIONS['options'])
            
            # yt-dlp → pipe → FFmpeg
            ytdlp_process = subprocess.Popen(
                [
                    'yt-dlp',
                    '--format', ydl_opts['format'], # Використовуємо формат з конфігу (opus HQ)
                    '--output', '-',
                    '--quiet', '--no-warnings',
                    url
                ],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
            )
            
            # Base audio filter: resampling + stable timestamps
            audio_filter = 'aresample=async=1:first_pts=0,asetpts=N/SR/TB'

            # MVP "AutoMix-style" fades (NOT an overlapped crossfade yet)
            try:
                fade_s = float(fade_seconds or 0.0)
            except Exception:
                fade_s = 0.0
            if fade_s > 0:
                if fade_in:
                    audio_filter += f',afade=t=in:st=0:d={fade_s}'
                if fade_out:
                    dur = track_dict.get('duration')
                    if isinstance(dur, (int, float)) and dur and dur > fade_s:
                        st = max(0.0, float(dur) - fade_s)
                        audio_filter += f',afade=t=out:st={st}:d={fade_s}'

            ffmpeg_cmd = [
                'ffmpeg',
                '-fflags', '+discardcorrupt',
                '-nostdin',
                '-i', 'pipe:0',
                '-f', 's16le',
                '-af', audio_filter,
            ] + ffmpeg_opts_list + ['pipe:1'] # Додаємо опції з config.py (rate, channels, etc)
            
            ffmpeg_process = subprocess.Popen(
                ffmpeg_cmd,
                stdin=ytdlp_process.stdout,
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                bufsize=4*1024*1024
            )
            
            ytdlp_process.stdout.close()
            
            source = YTDLPPipeSource(ytdlp_process, ffmpeg_process)
            logging.info(f"Audio pipeline started for: {track_dict.get('title', 'Unknown')}")
            return cls(source, data=track_dict)

        except Exception as e:
            logging.error(f"Error in from_track_dict: {str(e)}", exc_info=True)
            return None