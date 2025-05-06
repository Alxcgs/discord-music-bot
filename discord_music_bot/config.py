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
YDL_OPTIONS = {
    'format': 'bestaudio/best',
    'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'auto',
    'source_address': '0.0.0.0' # bind to ipv4 since ipv6 addresses cause issues sometimes
}

# --- Опції для FFmpeg ---
FFMPEG_OPTIONS = {
    # 'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5', # Видалено для тестування
    'options': '-vn' # -vn означає "без відео"
}

# --- Налаштування інтентів бота ---
# intents = discord.Intents.default() # Це буде в main.py
# intents.message_content = True
# intents.members = True
# intents.voice_states = True