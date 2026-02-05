import discord
import asyncio
from discord_music_bot.audio_source import YTDLSource
import logging

class PlayerService:
    def __init__(self):
        self.logger = logging.getLogger('MusicBot.PlayerService')

    async def play_stream(self, voice_client: discord.VoiceClient, url: str, loop: asyncio.AbstractEventLoop, after_callback) -> YTDLSource:
        """Creates a player and starts playing on the voice client."""
        try:
            player = await YTDLSource.from_url(url, loop=loop, stream=True)
            if player is None:
                raise ValueError(f"Failed to create audio source for URL: {url}")
            voice_client.play(player, after=after_callback)
            return player
        except Exception as e:
            self.logger.error(f"Error creating stream: {e}", exc_info=True)
            raise e

    def pause(self, voice_client: discord.VoiceClient):
        if voice_client and voice_client.is_playing():
            voice_client.pause()

    def resume(self, voice_client: discord.VoiceClient):
        if voice_client and voice_client.is_paused():
            voice_client.resume()

    def stop(self, voice_client: discord.VoiceClient):
        if voice_client and (voice_client.is_playing() or voice_client.is_paused()):
            voice_client.stop()

    def is_playing(self, voice_client: discord.VoiceClient) -> bool:
        return voice_client and voice_client.is_playing()

    def is_paused(self, voice_client: discord.VoiceClient) -> bool:
        return voice_client and voice_client.is_paused()
