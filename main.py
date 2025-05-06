import discord
from discord.ext import commands
import asyncio
import logging
import os
import ssl
import certifi
import discord.opus # <-- Додано імпорт
from discord_music_bot.config import DISCORD_TOKEN # Імпортуємо токен з конфігурації

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
    
    # Завантаження бібліотеки Opus
    opus_path = '/opt/homebrew/Cellar/opus/1.5.2/lib/libopus.dylib' # Перевірте цей шлях!
    if not discord.opus.is_loaded():
        try:
            discord.opus.load_opus(opus_path)
            logging.info(f"Бібліотеку Opus успішно завантажено з: {opus_path}")
        except discord.OpusNotLoaded:
            logging.warning(f"Не вдалося знайти бібліотеку Opus за шляхом {opus_path}. Перевірте шлях або встановіть Opus. Голосові функції можуть не працювати.")
        except Exception as e:
            logging.error(f"Сталася помилка під час завантаження Opus: {e}")
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