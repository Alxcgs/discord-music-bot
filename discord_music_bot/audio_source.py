import discord
import yt_dlp
import asyncio
import logging
from discord_music_bot.config import YDL_OPTIONS, FFMPEG_OPTIONS

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
        logging.info(f"Attempting to extract info for URL: {url} with stream={stream}")

        try:
            # Копіюємо опції, щоб не змінювати глобальні
            ydl_opts = YDL_OPTIONS.copy()
            
            # Якщо це пошуковий запит (не URL), додаємо "ytsearch:"
            if not url.startswith('http'):
                url = f"ytsearch:{url}"

            # Отримуємо інформацію про відео
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                try:
                    data = await loop.run_in_executor(None, lambda: ydl.extract_info(url, download=not stream))
                    logging.info(f"Successfully extracted info for URL: {url}")
                except Exception as e:
                    logging.error(f"Failed to extract info: {e}")
                    return None

            if data is None:
                logging.error("Failed to extract data from yt-dlp")
                return None

            # Якщо це результат пошуку, беремо перший результат
            if 'entries' in data:
                data = data['entries'][0]

            logging.info("Processing audio formats...")
            
            # Отримуємо URL для аудіо
            if stream:
                formats = data.get('formats', [])
                if not formats:
                    logging.error("No formats found in data")
                    return None

                logging.info(f"Found {len(formats)} formats")
                
                # Шукаємо аудіо формат
                audio_url = None
                
                # Спочатку шукаємо формат з тільки аудіо (m4a або mp3)
                for f in formats:
                    if not isinstance(f, dict):
                        continue
                        
                    format_id = f.get('format_id', '')
                    acodec = f.get('acodec', 'none')
                    vcodec = f.get('vcodec', 'none')
                    
                    logging.info(f"Checking format {format_id}: acodec={acodec}, vcodec={vcodec}")
                    
                    # Шукаємо формат, який містить тільки аудіо
                    if acodec != 'none' and vcodec == 'none':
                        audio_url = f.get('url')
                        if audio_url:
                            logging.info(f"Found audio-only format: {format_id}")
                            break
                
                # Якщо не знайшли чисте аудіо, шукаємо формат з найкращою якістю аудіо
                if not audio_url:
                    logging.info("No audio-only format found, searching for best audio quality")
                    best_audio = None
                    best_bitrate = 0
                    
                    for f in formats:
                        if not isinstance(f, dict):
                            continue
                            
                        acodec = f.get('acodec', 'none')
                        abr = f.get('abr', 0)
                        
                        if acodec != 'none' and abr > best_bitrate:
                            best_audio = f
                            best_bitrate = abr
                    
                    if best_audio:
                        audio_url = best_audio.get('url')
                        logging.info(f"Selected format with best audio quality: {best_audio.get('format_id')} (bitrate: {best_bitrate})")

                # Етап 3: Fallback на прямий URL з data (FFmpeg витягне аудіо автоматично)
                if not audio_url:
                    audio_url = data.get('url')
                    if audio_url:
                        logging.warning(f"Using fallback direct URL for '{data.get('title', 'unknown')}'")

                if not audio_url:
                    logging.error("Could not find valid audio URL in any format")
                    return None

                logging.info("Creating FFmpeg audio source...")
                try:
                    source = discord.FFmpegPCMAudio(audio_url, **FFMPEG_OPTIONS)
                    logging.info("Successfully created FFmpeg audio source")
                    return cls(source, data=data)
                except Exception as e:
                    logging.error(f"Error creating FFmpegPCMAudio: {e}")
                    return None
            else:
                logging.info("Download mode is not supported")
                return None

        except Exception as e:
            logging.error(f"Error in from_url: {str(e)}", exc_info=True)
            return None