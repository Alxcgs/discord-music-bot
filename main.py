import discord
from discord.ext import commands
import asyncio
import logging
import logging.handlers
import os
import sys
import ssl
import certifi
from discord_music_bot.config import DISCORD_TOKEN # Імпортуємо токен з конфігурації
from discord_music_bot.healthcheck import start_zombie_cleanup
import atexit

# --- Singleton Lock ---
LOCK_FILE = "discord_music_bot.lock"

def check_single_instance():
    """Перевіряє, чи не запущений вже бот, використовуючи pid-файл."""
    if os.path.exists(LOCK_FILE):
        try:
            with open(LOCK_FILE, 'r') as f:
                pid = int(f.read().strip())
            
            # Перевірка чи процес живий
            try:
                os.kill(pid, 0) # 0 signal just checks existence
                print(f"ERROR: Bot is already running (PID: {pid}). Exiting.")
                sys.exit(1)
            except OSError:
                print(f"WARNING: Lock file exists but process {pid} is dead. Cleaning up.")
                os.remove(LOCK_FILE)
        except (ValueError, FileNotFoundError):
            os.remove(LOCK_FILE)
            
    # Створюємо lock file
    with open(LOCK_FILE, 'w') as f:
        f.write(str(os.getpid()))
        
    def cleanup_lock():
        if os.path.exists(LOCK_FILE):
            os.remove(LOCK_FILE)
            
    atexit.register(cleanup_lock)

check_single_instance()

# --- Налаштування логування з ротацією ---
LOG_DIR = os.environ.get('LOG_DIR', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs'))
os.makedirs(LOG_DIR, exist_ok=True)

# Формат логів
log_formatter = logging.Formatter(
    '%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# Console handler
console_handler = logging.StreamHandler()
console_handler.setFormatter(log_formatter)
console_handler.setLevel(logging.INFO)

# File handler з ротацією: 5 файлів по 10MB
file_handler = logging.handlers.RotatingFileHandler(
    os.path.join(LOG_DIR, 'music_bot.log'),
    maxBytes=10 * 1024 * 1024,  # 10 MB
    backupCount=5,
    encoding='utf-8'
)
file_handler.setFormatter(log_formatter)
file_handler.setLevel(logging.INFO)

# Root logger
root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)
root_logger.addHandler(console_handler)
root_logger.addHandler(file_handler)

# Записати PID для Docker healthcheck
PID_FILE = os.path.join(os.environ.get('DB_DATA_DIR', 'data'), 'bot.pid')
os.makedirs(os.path.dirname(PID_FILE), exist_ok=True)
with open(PID_FILE, 'w') as f:
    f.write(str(os.getpid()))

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
    
    # Синхронізація Slash Commands
    try:
        synced = await bot.tree.sync()
        logging.info(f"Синхронізовано {len(synced)} Slash-команд.")
    except Exception as e:
        logging.error(f"Помилка синхронізації команд: {e}")

    # Встановлення статусу бота
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.listening, name="/play"))

    # Запуск zombie cleanup
    start_zombie_cleanup(asyncio.get_event_loop(), interval=300)

@bot.event
async def on_command_error(ctx, error):
    """Глобальний обробник помилок команд."""
    if isinstance(error, commands.CommandNotFound):
        await ctx.send("❓ Невідома команда. Використовуйте Slash-команди (почніть з `/`).")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"🤔 Не вистачає аргументів для команди `{ctx.command.name}`.")
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
    
    # Завантаження Opus (крос-платформенно)
    if not discord.opus.is_loaded():
        opus_paths = []
        if sys.platform == 'darwin':
            # macOS: homebrew ARM та Intel
            opus_paths = ['/opt/homebrew/lib/libopus.dylib', '/usr/local/lib/libopus.dylib']
        elif sys.platform == 'win32':
            # Windows: discord.py зазвичай знаходить автоматично
            opus_paths = []
        else:
            # Linux
            opus_paths = ['/usr/lib/x86_64-linux-gnu/libopus.so.0', '/usr/lib/libopus.so']
        
        loaded = False
        for path in opus_paths:
            try:
                discord.opus.load_opus(path)
                logging.info(f"Opus завантажено з: {path}")
                loaded = True
                break
            except Exception:
                continue
        
        if not loaded:
            try:
                discord.opus._load_default()
                logging.info("Opus завантажено (default)")
            except Exception as e:
                logging.warning(f"Не вдалося завантажити Opus: {e}")
    else:
        logging.info("Бібліотека Opus вже завантажена.")

    async with bot:
        await bot.start(DISCORD_TOKEN)

if __name__ == "__main__":
    # Перевірка токену перед запуском
    if not DISCORD_TOKEN:
        logging.error("Критична помилка: DISCORD_TOKEN не знайдено! Перевірте .env файл.")
    else:
        try:
            asyncio.run(main())
        except KeyboardInterrupt:
            logging.info("Бот вимикається...")
        except Exception as e:
            logging.critical(f"Критична помилка під час запуску бота: {e}")