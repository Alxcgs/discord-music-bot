import discord
import yt_dlp
import asyncio
import logging
import os # Додано імпорт os
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
        logging.info(f"Attempting to extract info for URL: {url} with stream={stream}") # Додано логування
        try:
            data = await loop.run_in_executor(None, lambda: yt_dlp.YoutubeDL(YDL_OPTIONS).extract_info(url, download=not stream))
            logging.info(f"Successfully extracted info for URL: {url}") # Додано логування
        except yt_dlp.utils.DownloadError as e:
             logging.error(f"Помилка завантаження yt-dlp: {e}")
             # Спробуємо ще раз з іншим форматом, якщо перший був 'best'
             if YDL_OPTIONS.get('format') == 'bestaudio/best': # Використовуємо .get для безпеки
                 logging.info("Спроба з форматом 'worstaudio'")
                 ydl_opts_worst = YDL_OPTIONS.copy()
                 ydl_opts_worst['format'] = 'worstaudio'
                 try:
                     data = await loop.run_in_executor(None, lambda: yt_dlp.YoutubeDL(ydl_opts_worst).extract_info(url, download=not stream))
                 except yt_dlp.utils.DownloadError as e2:
                     logging.error(f"Повторна помилка завантаження yt-dlp: {e2}")
                     return None
             else:
                return None

        if data is None:
             logging.error("Не вдалося отримати дані з yt-dlp.")
             return None

        try: # <-- Новий блок try
            # logging.info(f"Data extracted: {{k: v for k, v in data.items() if k != 'formats'}}") # Логування даних (без форматів) - Закоментовано для тестування
            logging.info("Data dictionary successfully created after extraction.") # Спрощене логування

            logging.info("Checking for 'entries' in data.") # Новий лог
            if 'entries' in data:
                # Беремо перший результат пошуку або плейлиста
                logging.info("Found 'entries' in data, taking the first one.") # Додано логування
                data = data['entries'][0]
                logging.info("Data updated after taking the first entry.") # Новий лог
            else:
                logging.info("\'entries\' not found in data.") # Новий лог

            # logging.info(f"Data before filename determination: {{k: v for k, v in data.items() if k != 'formats'}}") # Додаткове логування даних - Закоментовано
            logging.info("Passed 'entries' check.") # Новий простий лог

            filename = data.get('url') if stream else yt_dlp.YoutubeDL(YDL_OPTIONS).prepare_filename(data)
            logging.info(f"Determined filename/URL after potential prepare_filename: {filename}") # Оновлене логування

            if not filename:
                 logging.error("Не вдалося отримати URL або ім'я файлу з yt-dlp.")
                 return None

            # Перевіряємо, чи є 'url' в data перед використанням як filename
            # Це важливо, оскільки prepare_filename може повернути шлях до файлу
            audio_source_url = data.get('url')
            if not audio_source_url and not stream:
                logging.info(f"Audio source URL not found and stream=False. Checking if file exists: {filename}") # Додано логування
                # Якщо ми завантажували файл, filename має бути шляхом
                if not os.path.exists(filename):
                     logging.error(f"Завантажений файл не знайдено: {filename}")
                     return None
            elif stream and not audio_source_url:
                 logging.error("Не вдалося отримати URL аудіопотоку для стрімінгу.")
                 return None

            # Використовуємо audio_source_url для стрімінгу, filename для завантаженого файлу
            source_input = audio_source_url if stream else filename
            logging.info(f"Final source_input determined: {source_input}") # Додано логування остаточного джерела
            logging.info(f"Stream flag value: {stream}") # Логування значення stream
            logging.info(f"audio_source_url value: {audio_source_url}") # Логування значення audio_source_url

        except Exception as e:
            logging.error(f"Unexpected error processing data after extraction: {type(e).__name__} - {e}", exc_info=True)
            return None
        # <-- Кінець нового блоку try...except

        try:
            logging.info(f"Attempting to initialize FFmpegPCMAudio with source: {source_input} and options: {FFMPEG_OPTIONS}") # Детальне логування
            logging.debug(f"FFMPEG options being passed: {FFMPEG_OPTIONS}") # Логування опцій FFmpeg
            # --- Start FFmpeg Init --- 
            ffmpeg_audio = discord.FFmpegPCMAudio(source_input, **FFMPEG_OPTIONS)
            # --- End FFmpeg Init --- 
            logging.info(f"Successfully initialized FFmpegPCMAudio for: {source_input}") # Додано логування
            return cls(ffmpeg_audio, data=data)
        except discord.errors.ClientException as e:
            logging.error(f"Discord ClientException initializing FFmpegPCMAudio for {source_input}: {e}", exc_info=True)
            return None
        except Exception as e:
            logging.error(f"Generic Exception initializing FFmpegPCMAudio for {source_input}: {type(e).__name__} - {e}", exc_info=True) # Додано тип винятку
            return None