import os
from dotenv import load_dotenv
import logging

# Завантаження змінних середовища з .env файлу
load_dotenv()

# --- Конфігурація логування ---
logging.basicConfig(level=logging.INFO)

# --- Токен Discord ---
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')

if not DISCORD_TOKEN:
    logging.error("Помилка: Не знайдено DISCORD_TOKEN у .env файлі.")
    exit()

# --- Опції для yt-dlp ---
# --- Опції для yt-dlp (максимальна якість) ---
YDL_OPTIONS = {
    'format': 'bestaudio[acodec=opus][abr>=160]/bestaudio/best',
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
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn -ar 48000 -ac 2'
}

# --- Налаштування інтентів бота ---
# intents = discord.Intents.default() # Це буде в main.py
# intents.message_content = True
# intents.members = True
# intents.voice_states = True