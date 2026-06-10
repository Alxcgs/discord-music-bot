import os
from dotenv import load_dotenv
import logging
from discord_music_bot.ytdlp_config import YTDLP_AUDIO_FORMAT

# Завантаження змінних середовища з .env файлу
load_dotenv()

# --- Конфігурація логування ---
logging.basicConfig(level=logging.INFO)

# --- Токен Discord ---
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN', 'dummy_test_token')

if DISCORD_TOKEN == 'dummy_test_token':
    logging.warning("Увага: Не знайдено DISCORD_TOKEN у .env файлі. Тести будуть працювати, але реальний бот не запуститься.")

# --- Опції для yt-dlp ---
# --- Опції для yt-dlp (максимальна якість) ---
YDL_OPTIONS = {
    'format': YTDLP_AUDIO_FORMAT,
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'auto',
    'source_address': '0.0.0.0',
    'force-ipv4': True,
    'cachedir': False,
    'prefer_ffmpeg': True,
    'extract_flat': False,
}

# --- Опції для FFmpeg (найстабільніші налаштування) ---
FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -nostdin',
    'options': '-vn -ar 48000 -ac 2'
}

# --- Налаштування інтентів бота ---
# intents = discord.Intents.default() # Це буде в main.py
# intents.message_content = True
# intents.members = True
# intents.voice_states = True