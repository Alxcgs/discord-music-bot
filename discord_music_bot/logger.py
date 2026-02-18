"""
Модуль структурованого логування для Discord Music Bot.
Забезпечує кольоровий вивід у консоль та ротацію лог-файлів.
"""

import logging
import logging.handlers
import os
import sys


class ColorFormatter(logging.Formatter):
    """Кольоровий форматер для консольного виводу з emoji-маркерами."""

    COLORS = {
        logging.DEBUG:    '\033[90m',     # Сірий
        logging.INFO:     '\033[36m',     # Блакитний
        logging.WARNING:  '\033[33m',     # Жовтий
        logging.ERROR:    '\033[31m',     # Червоний
        logging.CRITICAL: '\033[1;31m',   # Яскраво-червоний (bold)
    }

    EMOJI = {
        logging.DEBUG:    '🔍',
        logging.INFO:     '💡',
        logging.WARNING:  '⚠️',
        logging.ERROR:    '❌',
        logging.CRITICAL: '🔥',
    }

    RESET = '\033[0m'

    def __init__(self, fmt=None, datefmt=None):
        super().__init__(fmt=fmt, datefmt=datefmt)

    def format(self, record):
        color = self.COLORS.get(record.levelno, self.RESET)
        emoji = self.EMOJI.get(record.levelno, '')
        # Додаємо кольори тільки для терміналу
        record.color_on = color
        record.color_off = self.RESET
        record.emoji = emoji
        return super().format(record)


def setup_logging(log_dir: str = None, level: int = logging.INFO) -> None:
    """
    Єдина точка налаштування логування для всього застосунку.

    Args:
        log_dir: Директорія для лог-файлів. За замовчуванням — ./logs/
        level: Мінімальний рівень логування.
    """
    if log_dir is None:
        log_dir = os.environ.get(
            'LOG_DIR',
            os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'logs')
        )
    os.makedirs(log_dir, exist_ok=True)

    root_logger = logging.getLogger()
    # Очищаємо хендлери щоб уникнути дублікатів при повторному виклику
    root_logger.handlers.clear()
    root_logger.setLevel(level)

    # ── Console Handler (кольоровий) ──────────────────────────────
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)

    if sys.stdout.isatty():
        # Інтерактивний термінал — кольори + emoji
        console_fmt = ColorFormatter(
            fmt='%(color_on)s%(emoji)s %(asctime)s [%(levelname)-8s]%(color_off)s %(name)s: %(message)s',
            datefmt='%H:%M:%S',
        )
    else:
        # Docker / pipe — без ANSI кодів
        console_fmt = logging.Formatter(
            fmt='%(asctime)s [%(levelname)-8s] %(name)s: %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S',
        )
    console_handler.setFormatter(console_fmt)
    root_logger.addHandler(console_handler)

    # ── File Handler (ротація: 5 файлів по 10MB) ──────────────────
    file_handler = logging.handlers.RotatingFileHandler(
        os.path.join(log_dir, 'music_bot.log'),
        maxBytes=10 * 1024 * 1024,  # 10 MB
        backupCount=5,
        encoding='utf-8',
    )
    file_handler.setLevel(level)
    file_fmt = logging.Formatter(
        fmt='%(asctime)s [%(levelname)-8s] %(name)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
    )
    file_handler.setFormatter(file_fmt)
    root_logger.addHandler(file_handler)

    # Зменшуємо шум від бібліотек
    logging.getLogger('discord').setLevel(logging.WARNING)
    logging.getLogger('discord.http').setLevel(logging.WARNING)
    logging.getLogger('yt_dlp').setLevel(logging.ERROR)

    root_logger.info('Логування налаштовано ✓')
