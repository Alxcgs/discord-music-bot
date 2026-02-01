"""
PlayerController - керування FFmpeg-відтворенням та відновленням після помилок.
"""
import asyncio
import logging
from typing import Callable, Optional

import discord

from discord_music_bot.audio_source import YTDLSource


class PlayerController:
    """
    Контролер відтворення: створює аудіо-джерела з повторними спробами,
    керує запуском FFmpeg-відтворення.
    """
    
    def __init__(self, bot, retry_count: int = 3, retry_delay: float = 2.0):
        self.bot = bot
        self.retry_count = retry_count
        self.retry_delay = retry_delay
        self.logger = logging.getLogger('PlayerController')
    
    async def create_player(self, url: str, *, stream: bool = True) -> Optional[YTDLSource]:
        """
        Створює аудіо-джерело з повторними спробами при помилках (yt-dlp, FFmpeg).
        """
        last_error = None
        for attempt in range(self.retry_count):
            try:
                player = await YTDLSource.from_url(
                    url,
                    loop=self.bot.loop,
                    stream=stream
                )
                if player:
                    if attempt > 0:
                        self.logger.info(f"Успішно після {attempt + 1} спроби")
                    return player
                last_error = Exception("yt-dlp не повернув аудіо-джерело")
            except Exception as e:
                last_error = e
            self.logger.warning(f"Спроба {attempt + 1}/{self.retry_count} не вдалась: {last_error}")
            if attempt < self.retry_count - 1:
                await asyncio.sleep(self.retry_delay)
        
        self.logger.error(f"Не вдалося створити плеєр після {self.retry_count} спроб: {last_error}")
        return None
    
    def play(
        self,
        voice_client: discord.VoiceClient,
        source: discord.AudioSource,
        *,
        after: Optional[Callable[[Optional[Exception]], None]] = None,
    ) -> None:
        """
        Запускає FFmpeg-відтворення. Callback after викликається по завершенню
        (з помилкою або без — при обриві потоку, збої FFmpeg тощо).
        """
        voice_client.play(source, after=after)
