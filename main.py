import discord
from discord.ext import commands
import asyncio
import ssl
import certifi
from dotenv import load_dotenv

# Завантаження змінних середовища з .env файлу
load_dotenv()

import logging
import os

# --- Конфігурація логування ---
logging.basicConfig(level=logging.INFO)

# --- Токен Discord ---
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')

# --- Опції для yt-dlp ---
YDL_OPTIONS = {
    'format': 'bestaudio[ext=m4a]/bestaudio[ext=mp3]/bestaudio',
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
    'extract_flat': False
}

# --- Опції для FFmpeg ---
FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -analyzeduration 0 -probesize 32768',
    'options': '-vn -acodec pcm_s16le -ar 48000 -ac 2'
}

# Налаштування інтентів (перенесено з bot.py/config.py)
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.voice_states = True

# Створення екземпляру бота
bot = commands.Bot(command_prefix='!', intents=intents)

# --- Завантаження когів ---
async def load_cogs():
    """Завантажує всі коги з папки 'discord_music_bot/cogs'."""
    cogs_path = './discord_music_bot/cogs'
    for filename in os.listdir(cogs_path):
        if filename.endswith('.py') and not filename.startswith('_'):
            try:
                await bot.load_extension(f'discord_music_bot.cogs.{filename[:-3]}')
                logging.info(f'Завантажено ког: {filename[:-3]}')
            except Exception as e:
                logging.error(f'Помилка завантаження кога {filename[:-3]}: {e}')

# --- Обробники подій бота ---
@bot.event
async def on_ready():
    """Викликається, коли бот готовий до роботи."""
    logging.info(f'Бот {bot.user.name} підключений до Discord!')
    logging.info(f'ID бота: {bot.user.id}')
    await load_cogs() # Завантажуємо коги після підключення
    # Встановлення статусу бота (опціонально)
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.listening, name="!help"))

@bot.event
async def on_command_error(ctx, error):
    """Глобальний обробник помилок команд."""
    if isinstance(error, commands.CommandNotFound):
        await ctx.send("❓ Невідома команда. Використовуйте `!help`, щоб побачити список команд.")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"🤔 Не вистачає аргументів для команди `{ctx.command.name}`. Перевірте `!help {ctx.command.name}`.")
    elif isinstance(error, commands.CheckFailure):
        await ctx.send("🚫 У вас недостатньо прав або умови для виконання цієї команди не виконані.")
    elif isinstance(error, commands.CommandInvokeError):
        original = error.original
        logging.error(f'В команді {ctx.command.name} виникла помилка: {original}')
        # Можна додати більш специфічну обробку для поширених помилок
        await ctx.send(f"❌ Сталася внутрішня помилка під час виконання команди. Повідомте розробника.\n`{original}`")
    else:
        logging.error(f'Необроблена помилка: {error}')
        await ctx.send(f"🤷‍♀️ Сталася невідома помилка: `{error}`")

# --- Запуск бота ---
async def main():
    # Налаштування SSL контексту
    ssl_context = ssl.create_default_context()
    ssl_context.load_verify_locations(cafile=certifi.where())
    
    # Перевірка наявності FFmpeg
    if not discord.opus.is_loaded():
        try:
            # На Windows discord.py автоматично знайде libopus
            discord.opus._load_default()
            logging.info("Бібліотеку Opus успішно завантажено")
        except Exception as e:
            logging.warning(f"Не вдалося завантажити бібліотеку Opus. Переконайтеся, що FFmpeg встановлено. Помилка: {e}")
    else:
        logging.info("Бібліотека Opus вже завантажена.")

    async with bot:
        await bot.start(DISCORD_TOKEN)

if __name__ == "__main__":
    # Перевірка токену перед запуском
    # if not DISCORD_TOKEN:
    #     logging.error("Критична помилка: DISCORD_TOKEN не знайдено! Перевірте .env файл.")
    # else:
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Бот вимикається...")
    except Exception as e:
        logging.critical(f"Критична помилка під час запуску бота: {e}")