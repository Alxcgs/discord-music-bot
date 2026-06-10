import discord
import yt_dlp
import asyncio
import subprocess
import logging
import shlex
import time
from discord_music_bot.config import YDL_OPTIONS, FFMPEG_OPTIONS
from discord_music_bot.ytdlp_config import build_ytdlp_cli_args

class YTDLPPipeSource(discord.AudioSource):
    """Аудіо source що використовує yt-dlp → FFmpeg pipeline.
    Буферизує дані щоб уникнути передчасного закінчення треку
    при тимчасових затримках в pipe."""
    
    FRAME_SIZE = 3840  # 20ms of 48kHz 16-bit stereo PCM
    MAX_READ_RETRIES = 150  # Кількість повторних спроб читання при неповному буфері (~15с толерантність)
    
    def __init__(self, ytdlp_process, ffmpeg_process):
        self._ytdlp = ytdlp_process
        self._ffmpeg = ffmpeg_process
        self._buffer = b''
        self._logged_failure = False

    @staticmethod
    def _read_stderr(process, name: str) -> str:
        if not process or not process.stderr:
            return ""
        try:
            raw = process.stderr.read()
            if not raw:
                return ""
            text = raw.decode("utf-8", errors="replace").strip()
            if text:
                logging.error(f"{name} stderr: {text[:4000]}")
            return text
        except Exception as exc:
            logging.warning(f"Could not read {name} stderr: {exc}")
            return ""

    def _log_pipeline_failure(self, reason: str):
        if self._logged_failure:
            return
        self._logged_failure = True
        logging.error(f"Audio pipeline stopped: {reason}")
        if self._ytdlp and self._ytdlp.poll() is not None:
            self._read_stderr(self._ytdlp, "yt-dlp")
        if self._ffmpeg and self._ffmpeg.poll() is not None:
            self._read_stderr(self._ffmpeg, "ffmpeg")
    
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
                    self._log_pipeline_failure(
                        f"ffmpeg exited with code {self._ffmpeg.returncode}"
                    )
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
                build_ytdlp_cli_args(url),
                stdout=subprocess.PIPE, stderr=subprocess.PIPE
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
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                bufsize=4*1024*1024
            )
            
            ytdlp_process.stdout.close()

            # Швидка перевірка: якщо subprocess впав одразу — логуємо stderr
            await asyncio.sleep(0.3)
            if ytdlp_process.poll() is not None:
                YTDLPPipeSource._read_stderr(
                    ytdlp_process,
                    f"yt-dlp (exit {ytdlp_process.returncode})",
                )
                raise RuntimeError(
                    f"yt-dlp exited immediately with code {ytdlp_process.returncode}"
                )
            if ffmpeg_process.poll() is not None:
                YTDLPPipeSource._read_stderr(
                    ffmpeg_process,
                    f"ffmpeg (exit {ffmpeg_process.returncode})",
                )
                raise RuntimeError(
                    f"ffmpeg exited immediately with code {ffmpeg_process.returncode}"
                )
            
            source = YTDLPPipeSource(ytdlp_process, ffmpeg_process)
            logging.info(
                f"Audio pipeline started for: {track_dict.get('title', 'Unknown')} "
                f"(yt-dlp pid={ytdlp_process.pid}, ffmpeg pid={ffmpeg_process.pid})"
            )
            return cls(source, data=track_dict)

        except Exception as e:
            logging.error(f"Error in from_track_dict: {str(e)}", exc_info=True)
            return None