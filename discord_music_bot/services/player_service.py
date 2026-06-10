import discord
import asyncio
from discord_music_bot.audio_source import YTDLSource
import logging

class PlayerService:
    def __init__(self):
        self.logger = logging.getLogger('MusicBot.PlayerService')

    async def play_stream(
        self,
        voice_client: discord.VoiceClient,
        track_dict: dict,
        loop: asyncio.AbstractEventLoop,
        after_callback,
        *,
        fade_seconds: float = 0.0,
        fade_in: bool = False,
        fade_out: bool = False,
    ) -> YTDLSource:
        """Creates a player and starts playing on the voice client."""
        try:
            # Check voice connection before attempting playback
            if not voice_client or not voice_client.is_connected():
                raise discord.errors.ClientException("Voice client is not connected — cannot start playback.")
            
            player = await YTDLSource.from_track_dict(
                track_dict,
                loop=loop,
                fade_seconds=fade_seconds,
                fade_in=fade_in,
                fade_out=fade_out,
            )
            if player is None:
                url = track_dict.get('webpage_url') or track_dict.get('url') or 'Unknown URL'
                raise ValueError(f"Failed to create audio source for URL: {url}")
            
            # Double-check connection (could have dropped during URL extraction)
            if not voice_client.is_connected():
                raise discord.errors.ClientException("Voice connection lost while preparing audio source.")

            def _after_playback(error):
                if error:
                    self.logger.error(f"Player error: {error}")
                else:
                    self.logger.info("Track finished")
                after_callback(error)

            voice_client.play(player, after=_after_playback)

            self.logger.info(f"Voice client connected: {voice_client.is_connected()}")
            self.logger.info(f"Voice client playing: {voice_client.is_playing()}")
            self.logger.info(f"Voice client paused: {voice_client.is_paused()}")
            if not voice_client.is_playing():
                self.logger.warning(
                    "Playback did not start — FFmpeg/yt-dlp pipeline may have failed; "
                    "check logs above for subprocess errors."
                )

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
