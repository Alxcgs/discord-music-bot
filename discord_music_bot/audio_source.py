import discord
import asyncio
import subprocess
import logging
import shlex
import time
from discord_music_bot.config import FFMPEG_OPTIONS
from discord_music_bot.ytdlp_config import extract_stream_url


class YTDLPPipeSource(discord.AudioSource):
    """Аудіо source: FFmpeg читає прямий media URL і віддає PCM у Discord.
    Буферизує дані щоб уникнути передчасного закінчення треку
    при тимчасових мережевих затримках."""

    FRAME_SIZE = 3840  # 20ms of 48kHz 16-bit stereo PCM
    MAX_READ_RETRIES = 150  # ~15s толерантність на порожні читання

    def __init__(self, ytdlp_process, ffmpeg_process):
        self._ytdlp = ytdlp_process  # legacy slot; None when streaming via direct URL
        self._ffmpeg = ffmpeg_process
        self._buffer = b""
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
        retries = 0
        while len(self._buffer) < self.FRAME_SIZE:
            chunk = self._ffmpeg.stdout.read(self.FRAME_SIZE - len(self._buffer))
            if chunk:
                self._buffer += chunk
                retries = 0
            else:
                if self._ffmpeg.poll() is not None:
                    self._log_pipeline_failure(
                        f"ffmpeg exited with code {self._ffmpeg.returncode}"
                    )
                    if self._buffer:
                        frame = self._buffer.ljust(self.FRAME_SIZE, b"\x00")
                        self._buffer = b""
                        return frame
                    return b""

                retries += 1
                if retries >= self.MAX_READ_RETRIES:
                    if self._buffer:
                        frame = self._buffer.ljust(self.FRAME_SIZE, b"\x00")
                        self._buffer = b""
                        return frame
                    return b""
                time.sleep(0.1)

        frame = self._buffer[: self.FRAME_SIZE]
        self._buffer = self._buffer[self.FRAME_SIZE :]
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
        self.title = data.get("title")
        self.url = data.get("webpage_url")
        self.duration = data.get("duration")
        self.thumbnail = data.get("thumbnail")

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
        """Створює YTDLSource: yt-dlp API → direct URL → FFmpeg PCM pipe."""
        if not track_dict:
            logging.error("No track metadata provided")
            return None

        loop = loop or asyncio.get_event_loop()

        url = track_dict.get("webpage_url") or track_dict.get("url")
        if not url:
            logging.error("No URL provided in track_dict")
            return None

        logging.info(f"Creating audio pipeline for: {track_dict.get('title', 'Unknown')}")

        try:
            stream_url, info = await loop.run_in_executor(
                None, lambda: extract_stream_url(url)
            )
            if not stream_url:
                raise RuntimeError(f"Could not resolve stream URL for {url}")

            merged = dict(track_dict)
            if info:
                merged.setdefault("title", info.get("title"))
                merged.setdefault("webpage_url", info.get("webpage_url") or url)
                merged.setdefault("duration", info.get("duration"))
                merged.setdefault("thumbnail", info.get("thumbnail"))

            ffmpeg_opts_list = shlex.split(FFMPEG_OPTIONS["options"])
            before_opts_list = shlex.split(FFMPEG_OPTIONS["before_options"])

            audio_filter = "aresample=async=1:first_pts=0,asetpts=N/SR/TB"

            try:
                fade_s = float(fade_seconds or 0.0)
            except Exception:
                fade_s = 0.0
            if fade_s > 0:
                if fade_in:
                    audio_filter += f",afade=t=in:st=0:d={fade_s}"
                if fade_out:
                    dur = merged.get("duration")
                    if isinstance(dur, (int, float)) and dur and dur > fade_s:
                        st = max(0.0, float(dur) - fade_s)
                        audio_filter += f",afade=t=out:st={st}:d={fade_s}"

            ffmpeg_cmd = (
                [
                    "ffmpeg",
                    "-fflags",
                    "+discardcorrupt",
                    "-nostdin",
                ]
                + before_opts_list
                + [
                    "-i",
                    stream_url,
                    "-f",
                    "s16le",
                    "-af",
                    audio_filter,
                ]
                + ffmpeg_opts_list
                + ["pipe:1"]
            )

            ffmpeg_process = subprocess.Popen(
                ffmpeg_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=4 * 1024 * 1024,
            )

            await asyncio.sleep(0.3)
            if ffmpeg_process.poll() is not None:
                YTDLPPipeSource._read_stderr(
                    ffmpeg_process,
                    f"ffmpeg (exit {ffmpeg_process.returncode})",
                )
                raise RuntimeError(
                    f"ffmpeg exited immediately with code {ffmpeg_process.returncode}"
                )

            source = YTDLPPipeSource(None, ffmpeg_process)
            logging.info(
                f"Audio pipeline started for: {merged.get('title', 'Unknown')} "
                f"(ffmpeg pid={ffmpeg_process.pid})"
            )
            return cls(source, data=merged)

        except Exception as e:
            logging.error(f"Error in from_track_dict: {str(e)}", exc_info=True)
            return None
