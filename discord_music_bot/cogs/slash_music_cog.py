import discord
from discord import app_commands
from discord.ext import commands
import asyncio
import logging
from discord_music_bot.services.queue_service import QueueService
from discord_music_bot.services.history_service import HistoryService
from discord_music_bot.services.player_service import PlayerService
from discord_music_bot.audio_source import YTDLSource
from discord_music_bot.utils import format_duration
from discord_music_bot.database import init_db
from discord_music_bot.repository import MusicRepository
from discord_music_bot.services.auto_resume import auto_resume
from discord_music_bot.views.dismiss_view import DismissView
from discord_music_bot.views.history_view import HistoryView
from discord_music_bot.views.music_controls import MusicControls
from discord_music_bot.views.queue_view import QueueView
from discord_music_bot.views.search_results_view import SearchResultsView
import yt_dlp
from discord_music_bot import consts


class MusicCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.repository = MusicRepository()
        self.queue_service = QueueService(self.repository)
        self.history_service = HistoryService(self.repository)
        self.player_service = PlayerService()
        self.current_song = {}
        self.control_messages = {}
        self.player_channels = {}
        self.processing_buttons = set()
        self._skip_after_play = set()  # guild_ids де after-callback має бути пропущений
        self._session_tracks = {}  # {guild_id: [track_dicts]} — треки за поточну сесію
        self._guild_volumes = {}  # {guild_id: float} — збережена гучність (0.0-2.0)
        self.logger = logging.getLogger('MusicBot')
        self.logger.setLevel(logging.INFO)
        
        self.light_ydl_opts = consts.YTDL_OPTIONS_LIGHT

    async def cog_load(self):
        """Викликається при завантаженні когу — ініціалізує БД та запускає auto-resume."""
        await init_db()
        self.logger.info("БД ініціалізована, ког MusicCog завантажений.")
        # Auto-resume запускається після готовності бота (чекаємо on_ready)
        self.bot.add_listener(self._on_ready_auto_resume, 'on_ready')

    async def _on_ready_auto_resume(self):
        """Запускає auto-resume після повної готовності бота."""
        await asyncio.sleep(3)  # Невелика затримка для стабільності
        count = await auto_resume(self.bot, self)
        if count > 0:
            self.logger.info(f"Auto-Resume: відновлено {count} сервер(ів).")

    async def get_video_info(self, url):
        search_url = url if any(x in url.lower() for x in ['youtube.com', 'youtu.be', 'soundcloud.com']) else f"ytsearch:{url}"
        # SoundCloud потребує повної екстракції для отримання назв
        is_soundcloud = 'soundcloud.com' in url.lower()
        ydl_opts = self.light_ydl_opts.copy()
        if is_soundcloud:
            ydl_opts['extract_flat'] = False
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            try:
                info = await self.bot.loop.run_in_executor(None, lambda: ydl.extract_info(search_url, download=False))
                if not info: return None
                if 'entries' in info: info = info['entries'][0]
                return {
                    'title': info.get('title') or info.get('fulltitle') or 'Unknown',
                    'url': info.get('webpage_url', url) or info.get('url', url),
                    'duration': info.get('duration'),
                    'thumbnail': info.get('thumbnail')
                }
            except Exception as e:
                self.logger.error(f"Error extracting info: {e}")
                return None

    async def search_videos(self, query, max_results=10):
        """Шукає кілька відео за текстовим запитом для меню вибору."""
        search_url = f"ytsearch{max_results}:{query}"
        with yt_dlp.YoutubeDL(self.light_ydl_opts) as ydl:
            try:
                info = await self.bot.loop.run_in_executor(None, lambda: ydl.extract_info(search_url, download=False))
                if not info or 'entries' not in info:
                    return []
                results = []
                for entry in info['entries']:
                    if entry:
                        results.append({
                            'title': entry.get('title', 'Unknown'),
                            'url': entry.get('webpage_url', entry.get('url', '')),
                            'webpage_url': entry.get('webpage_url', entry.get('url', '')),
                            'duration': entry.get('duration'),
                            'thumbnail': entry.get('thumbnail')
                        })
                return results
            except Exception as e:
                self.logger.error(f"Error searching videos: {e}")
                return []

    async def extract_playlist(self, url):
        """Витягує список треків з плейлиста (тільки метадані, швидко)."""
        # SoundCloud не підтримує extract_flat — використовуємо повну екстракцію
        is_soundcloud = 'soundcloud.com' in url.lower()
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False if is_soundcloud else 'in_playlist',
            'skip_download': True,
            'ignoreerrors': True,
        }
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = await self.bot.loop.run_in_executor(
                    None, lambda: ydl.extract_info(url, download=False)
                )
                if not info or 'entries' not in info:
                    return None, []

                playlist_title = info.get('title', 'Плейлист')
                tracks = []
                for entry in info['entries']:
                    if not entry:
                        continue
                    track_url = entry.get('url') or entry.get('webpage_url', '')
                    if not track_url:
                        continue
                    # Для flat extraction URL може бути ID — конвертуємо у повний URL
                    if not track_url.startswith('http'):
                        track_url = f"https://www.youtube.com/watch?v={track_url}"
                    tracks.append({
                        'title': entry.get('title', 'Unknown'),
                        'url': track_url,
                        'duration': entry.get('duration'),
                        'thumbnail': None,
                    })
                return playlist_title, tracks
        except Exception as e:
            self.logger.error(f"Error extracting playlist: {e}")
            return None, []

    async def update_player(self, guild, channel):
        try:
            guild_id = guild.id
            embed = discord.Embed(title="🎵 Музичний плеєр", color=consts.COLOR_EMBED_PLAYING)
            
            if guild_id in self.current_song:
                song = self.current_song[guild_id]
                requester_text = f"\nЄ️ {song['requester'].mention}" if song.get('requester') else ""
                embed.add_field(name="🎶 Зараз грає", value=f"[{song['title']}]({song['url']}){requester_text}", inline=False)
                if song.get('thumbnail'): embed.set_thumbnail(url=song['thumbnail'])
            else:
                embed.add_field(name="🎶 Зараз грає", value="Нічого не грає", inline=False)

            queue = self.queue_service.get_queue(guild_id)
            q_text = "\n".join([f"`{i+1}.` {t['title']}" for i, t in enumerate(queue[:consts.PREVIEW_QUEUE_SIZE])]) or "Черга порожня"
            embed.add_field(name="📑 Далі", value=q_text, inline=False)

            view = MusicControls(self, guild)
            
            if guild_id in self.control_messages:
                try:
                    old = await channel.fetch_message(self.control_messages[guild_id])
                    await old.delete()
                except: pass
            
            msg = await channel.send(embed=embed, view=view)
            self.control_messages[guild_id] = msg.id
            self.player_channels[guild_id] = channel.id
        except Exception as e:
            self.logger.error(f"Update player error: {e}")

    async def _force_voice_cleanup(self, guild):
        """Примусово очищає будь-яке існуюче voice з'єднання для гільдії."""
        voice_client = guild.voice_client
        if voice_client:
            self.logger.info(f"Force cleanup: disconnecting stale voice client for {guild.name}")
            try:
                if voice_client.is_playing():
                    voice_client.stop()
                await voice_client.disconnect(force=True)
            except Exception as e:
                self.logger.warning(f"Force cleanup error (ignorable): {e}")
            # Даємо Discord час очистити стару сесію
            await asyncio.sleep(5)

    async def _ensure_voice_connected(self, voice_client, guild):
        """Перевіряє voice з'єднання та намагається одноразовий reconnect якщо не підключений."""
        if voice_client and voice_client.is_connected():
            return voice_client
        
        # Спробувати reconnect
        channel = voice_client.channel if voice_client else None
        if not channel:
            self.logger.error(f"Cannot reconnect: no voice channel reference for guild {guild.id}")
            return None
        
        self.logger.warning(f"Voice not connected for guild {guild.name}, attempting single reconnect...")
        
        # Force cleanup stale connection first
        await self._force_voice_cleanup(guild)
        
        try:
            new_vc = await channel.connect(timeout=consts.TIMEOUT_VOICE_CONNECT, reconnect=True)
            if new_vc and new_vc.is_connected():
                self.logger.info(f"Reconnected to {channel.name} ({guild.name})")
                return new_vc
        except Exception as e:
            self.logger.error(f"Reconnect failed for {guild.name}: {e}")
        
        return None

    async def play_next_song(self, guild, voice_client):
        try:
            guild_id = guild.id
            if guild_id in self.current_song:
                # Додаємо в історію через HistoryService (зберігає і в пам'ять, і в БД)
                song = self.current_song[guild_id]
                # Нормалізуємо дані трека — гарантуємо url і webpage_url
                history_track = {
                    'title': song.get('title', 'Unknown'),
                    'url': song.get('url') or song.get('webpage_url', ''),
                    'webpage_url': song.get('webpage_url') or song.get('url', ''),
                    'duration': song.get('duration'),
                    'thumbnail': song.get('thumbnail'),
                    'requester': song.get('requester'),
                }
                self.history_service.add_to_history(guild_id, history_track)
            
            queue = self.queue_service.get_queue(guild_id)
            if queue:
                # Ensure voice is connected before trying to play
                voice_client = await self._ensure_voice_connected(voice_client, guild)
                if not voice_client:
                    self.logger.error(f"Cannot play: voice not connected for guild {guild.name}")
                    if guild_id in self.player_channels:
                        channel = self.bot.get_channel(self.player_channels[guild_id])
                        if channel:
                            await channel.send("❌ Не вдалося підключитися до голосового каналу. Скористайтеся `/play` знову.")
                    return
                
                item = self.queue_service.get_next_track(guild_id)
                try:
                    player = await self.player_service.play_stream(
                        voice_client, 
                        item['url'], 
                        self.bot.loop, 
                        lambda e: self.bot.loop.create_task(self.check_after_play(guild, voice_client, e))
                    )
                    
                    # Застосовуємо збережену гучність
                    if guild_id in self._guild_volumes:
                        player.volume = self._guild_volumes[guild_id]
                    
                    self.current_song[guild_id] = {
                        'title': player.title, 'url': player.url, 'thumbnail': player.thumbnail,
                        'duration': player.duration, 'requester': item.get('requester'), 'player': player
                    }
                    
                    # Зберігаємо трек у сесійну статистику
                    if guild_id not in self._session_tracks:
                        self._session_tracks[guild_id] = []
                    self._session_tracks[guild_id].append({
                        'title': player.title, 'url': player.url,
                        'duration': player.duration,
                    })
                    
                    # Зберігаємо стан у БД для auto-resume
                    voice_channel_id = voice_client.channel.id if voice_client.channel else None
                    text_channel_id = self.player_channels.get(guild_id)
                    asyncio.ensure_future(self.repository.save_guild_state(
                        guild_id=guild_id,
                        voice_channel_id=voice_channel_id,
                        text_channel_id=text_channel_id,
                        track_url=player.url,
                        track_title=player.title,
                        track_duration=player.duration,
                        track_thumbnail=player.thumbnail,
                        is_paused=False,
                    ))
                    
                    if guild_id in self.player_channels:
                        channel = self.bot.get_channel(self.player_channels[guild_id])
                        if channel: await self.update_player(guild, channel)
                    
                    
                except Exception as track_error:
                    self.logger.error(f"Failed to play track '{item.get('title', 'Unknown')}': {track_error}")
                    # Try next track instead of stopping
                    if voice_client.is_connected():
                        await self.play_next_song(guild, voice_client)
            else:
                if guild_id in self.current_song: del self.current_song[guild_id]
                # Очищаємо стан у БД — нічого не грає
                asyncio.ensure_future(self.repository.clear_guild_state(guild_id))
                if guild_id in self.player_channels:
                    channel = self.bot.get_channel(self.player_channels[guild_id])
                    if channel: await self.update_player(guild, channel)
                await asyncio.sleep(consts.TIMEOUT_VOICE_DISCONNECT)
                if not self.player_service.is_playing(voice_client) and not self.queue_service.get_queue(guild_id):
                    await voice_client.disconnect()
        except Exception as e:
            self.logger.error(f"Play next error: {e}")

    async def check_after_play(self, guild, voice_client, error):
        if error:
            self.logger.error(f"Playback error in guild {guild.id}: {error}")
        # Якщо прапорець встановлено (напр. кнопка "Попередній"), пропускаємо play_next_song
        if guild.id in self._skip_after_play:
            self.logger.info(f"check_after_play: skipped for guild {guild.id} (previous button)")
            return
        if voice_client.is_connected():
            await self.play_next_song(guild, voice_client)


    async def leave_logic(self, guild):
        voice_client = guild.voice_client
        if voice_client:
            self.queue_service.clear(guild.id)
            if guild.id in self.current_song: del self.current_song[guild.id]
            # Очищаємо стан у БД
            await self.repository.clear_guild_state(guild.id)
            await voice_client.disconnect()

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        # 1. Bot disconnected manually or kicked
        if member.id == self.bot.user.id and after.channel is None:
             self.queue_service.clear(member.guild.id)
             if member.guild.id in self.current_song: del self.current_song[member.guild.id]
             asyncio.ensure_future(self.repository.clear_guild_state(member.guild.id))
             return

        # 2. Someone left the bot's channel
        voice_client = member.guild.voice_client
        if voice_client and voice_client.channel and before.channel == voice_client.channel:
            # Check if bot is alone
            if len(voice_client.channel.members) == 1:
                # Wait to see if someone comes back
                await asyncio.sleep(consts.TIMEOUT_EMPTY_CHANNEL)
                
                # Check again
                if voice_client.is_connected() and len(voice_client.channel.members) == 1:
                    voice_client.stop()
                    await voice_client.disconnect()
                    
                    # Cleanup
                    self.queue_service.clear(member.guild.id)
                    if member.guild.id in self.current_song: del self.current_song[member.guild.id]

                    # Notify text channel if known
                    if member.guild.id in self.player_channels:
                        channel = self.bot.get_channel(self.player_channels[member.guild.id])
                        if channel:
                            await channel.send("👻 Всі пішли, тому я теж пішов. (10с тиші)")

    @app_commands.command(name="join", description="Підключити бота до голосового каналу")
    async def join(self, interaction: discord.Interaction):
        if not interaction.user.voice:
            await interaction.response.send_message("Ви не в голосовому каналі!", ephemeral=True)
            return
        
        channel = interaction.user.voice.channel
        voice_client = interaction.guild.voice_client

        await interaction.response.defer()

        if voice_client and voice_client.is_connected():
            if voice_client.channel != channel:
                await voice_client.move_to(channel)
                await interaction.followup.send(f"Перемістився до {channel.mention}")
            else:
                await interaction.followup.send("Я вже тут!", ephemeral=True)
        else:
            await self._force_voice_cleanup(interaction.guild)
            await channel.connect(timeout=consts.TIMEOUT_VOICE_CONNECT, reconnect=True)
            self.player_channels[interaction.guild.id] = interaction.channel.id # Save channel for notifications
            await interaction.followup.send(f"Приєднався до {channel.mention}")

    @app_commands.command(name="play", description="Відтворити музику (URL або пошук)")
    @app_commands.describe(query="Посилання або назва пісні")
    async def play(self, interaction: discord.Interaction, query: str):
        if not interaction.user.voice:
            await interaction.response.send_message("Зайдіть у голосовий канал!", ephemeral=True)
            return

        await interaction.response.defer()
        
        voice_client = interaction.guild.voice_client
        if not voice_client:
            # Force cleanup any stale session before connecting (prevents 4017)
            await self._force_voice_cleanup(interaction.guild)
            voice_client = await interaction.user.voice.channel.connect(timeout=consts.TIMEOUT_VOICE_CONNECT, reconnect=True)
        
        # Verify connection is actually established
        if not voice_client or not voice_client.is_connected():
            voice_client = await self._ensure_voice_connected(voice_client, interaction.guild)
            if not voice_client:
                await interaction.followup.send("❌ Не вдалося підключитися до голосового каналу. Спробуйте ще раз.")
                return
        
        self.player_channels[interaction.guild.id] = interaction.channel.id # Save channel for notifications
        # Check for playlist
        is_playlist = 'list=' in query or '/sets/' in query or '/playlist' in query
        if is_playlist:
            playlist_title, tracks = await self.extract_playlist(query)
            if not tracks:
                await interaction.followup.send("❌ Не вдалося завантажити плейлист або він порожній.")
                return

            # Обмежуємо розмір плейлиста
            tracks = tracks[:consts.MAX_PLAYLIST_SIZE]
            for t in tracks:
                t['requester'] = interaction.user

            self.queue_service.add_tracks(interaction.guild.id, tracks)
            await interaction.followup.send(
                f"{consts.EMOJI_PLAYLIST} Плейлист **{playlist_title}** — додано **{len(tracks)}** треків у чергу!"
            )

            await self.update_player(interaction.guild, interaction.channel)
            if not self.player_service.is_playing(voice_client) and not self.player_service.is_paused(voice_client):
                await self.play_next_song(interaction.guild, voice_client)
            return

        is_url = query.startswith('http') or any(x in query.lower() for x in ['youtube.com', 'youtu.be', 'soundcloud.com'])
        
        if is_url:
            # Пряме посилання — додаємо одразу
            info = await self.get_video_info(query)
            if not info:
                await interaction.followup.send("❌ Не вдалося знайти трек.")
                return
            info['requester'] = interaction.user
            self.queue_service.add_track(interaction.guild.id, info)
            await interaction.followup.send(f"✅ Додано: **{info['title']}**")
        else:
            # Текстовий запит — показуємо меню вибору
            results = await self.search_videos(query)
            if not results:
                await interaction.followup.send("❌ Не вдалося знайти треки за запитом.")
                return
            
            view = SearchResultsView(self, interaction.user, results)
            msg = await interaction.followup.send(embed=view.create_embed(), view=view)
            
            # Чекаємо вибір користувача
            timed_out = await view.wait()
            
            if timed_out or view.selected_track is None:
                return
            
            info = view.selected_track
            info['requester'] = interaction.user
            self.queue_service.add_track(interaction.guild.id, info)
            await interaction.channel.send(f"✅ Додано: **{info['title']}**")
        
        await self.update_player(interaction.guild, interaction.channel)
        
        if not self.player_service.is_playing(voice_client) and not self.player_service.is_paused(voice_client):
            await self.play_next_song(interaction.guild, voice_client)

    @app_commands.command(name="skip", description="Пропустити трек")
    async def skip(self, interaction: discord.Interaction):
        voice_client = interaction.guild.voice_client
        if voice_client and (voice_client.is_playing() or voice_client.is_paused()):
            voice_client.stop()
            await interaction.response.send_message(f"⏭️ Пропущено {interaction.user.mention}.")
        else:
            await interaction.response.send_message("Нічого пропускати.", ephemeral=True)

    @app_commands.command(name="pause", description="Поставити на паузу")
    async def pause(self, interaction: discord.Interaction):
        voice_client = interaction.guild.voice_client
        if voice_client and voice_client.is_playing():
            voice_client.pause()
            await interaction.response.send_message("⏸️ Пауза.")
        else:
            await interaction.response.send_message("Нічого ставити на паузу.", ephemeral=True)

    @app_commands.command(name="resume", description="Продовжити відтворення")
    async def resume(self, interaction: discord.Interaction):
        voice_client = interaction.guild.voice_client
        if voice_client and voice_client.is_paused():
            voice_client.resume()
            await interaction.response.send_message("▶️ Продовжуємо.")
        else:
            await interaction.response.send_message("Нічого відновлювати.", ephemeral=True)

    @app_commands.command(name="reset", description="Скинути бота (якщо зависне)")
    async def reset(self, interaction: discord.Interaction):
        guild = interaction.guild
        voice_client = guild.voice_client
        self.queue_service.clear(guild.id)
        if guild.id in self.current_song: del self.current_song[guild.id]
        await self.repository.clear_guild_state(guild.id)
        if voice_client:
            try:
                voice_client.stop()
                await voice_client.disconnect(force=True)
            except: pass
        await interaction.response.send_message("🔄 Бот скинуто. Можна використовувати /play знову.")

    @app_commands.command(name="stop", description="Зупинити відтворення")
    async def stop(self, interaction: discord.Interaction):
        voice_client = interaction.guild.voice_client
        if voice_client:
            voice_client.stop()
            self.queue_service.clear(interaction.guild.id)
            if interaction.guild.id in self.current_song: del self.current_song[interaction.guild.id]
            await self.repository.clear_guild_state(interaction.guild.id)
            await interaction.response.send_message("⏹️ Зупинено.")
        else:
            await interaction.response.send_message("Бот не грає.", ephemeral=True)

    @app_commands.command(name="queue", description="Показати чергу")
    async def queue(self, interaction: discord.Interaction):
        view = QueueView(self, interaction.guild)
        await interaction.response.send_message(embed=view.create_embed(), view=view, ephemeral=True)

    @app_commands.command(name="shuffle", description="Перемішати чергу")
    async def shuffle(self, interaction: discord.Interaction):
        guild_id = interaction.guild.id
        queue = self.queue_service.get_queue(guild_id)
        if len(queue) < 2:
            await interaction.response.send_message("Недостатньо треків.", ephemeral=True)
            return
        self.queue_service.shuffle(guild_id)
        await interaction.response.send_message(f"🔀 Чергу перемішано ({len(queue)} треків).")
        await self.update_player(interaction.guild, interaction.channel)

    @app_commands.command(name="move", description="Перемістити трек у черзі")
    @app_commands.describe(from_pos="З якої позиції", to_pos="На яку позицію")
    async def move(self, interaction: discord.Interaction, from_pos: int, to_pos: int):
        guild_id = interaction.guild.id
        queue = self.queue_service.get_queue(guild_id)
        if not queue:
            await interaction.response.send_message("Черга порожня.", ephemeral=True)
            return
        if from_pos < 1 or from_pos > len(queue) or to_pos < 1 or to_pos > len(queue):
            await interaction.response.send_message(
                f"❗ Некоректні позиції. Допустимий діапазон: **1–{len(queue)}**.", ephemeral=True
            )
            return
        if from_pos == to_pos:
            await interaction.response.send_message("Трек вже на цій позиції.", ephemeral=True)
            return

        track = self.queue_service.move_track(guild_id, from_pos, to_pos)
        if track:
            direction = "⬆️" if to_pos < from_pos else "⬇️"
            await interaction.response.send_message(
                f"{direction} Переміщено **{track.get('title', '?')[:40]}**: #{from_pos} → #{to_pos}"
            )
            await self.update_player(interaction.guild, interaction.channel)
        else:
            await interaction.response.send_message("❗ Помилка переміщення.", ephemeral=True)

    @app_commands.command(name="leave", description="Вигнати бота")
    async def leave(self, interaction: discord.Interaction):
        if not interaction.guild.voice_client:
            await interaction.response.send_message("Бот не в голосовому каналі.", ephemeral=True)
            return
        await self.leave_logic(interaction.guild)
        await interaction.response.send_message("👋 Бувай!")

    @app_commands.command(name="volume", description="Встановити гучність (0-200%)")
    @app_commands.describe(level="Гучність у відсотках (0-200)")
    async def volume(self, interaction: discord.Interaction, level: int):
        voice_client = interaction.guild.voice_client
        if not voice_client or not voice_client.source or not hasattr(voice_client.source, 'volume'):
            await interaction.response.send_message("Зараз нічого не грає.", ephemeral=True)
            return
        
        clamped = max(0, min(200, level))
        voice_client.source.volume = clamped / 100.0
        self._guild_volumes[interaction.guild.id] = clamped / 100.0
        emoji = "🔇" if clamped == 0 else "🔉" if clamped < 50 else "🔊"
        await interaction.response.send_message(f"{emoji} Гучність встановлена: **{clamped}%**")

    @app_commands.command(name="stats", description="Статистика прослуховування сервера")
    async def stats(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild_id = interaction.guild_id

        try:
            top_tracks = await self.repository.get_top_tracks(guild_id, limit=10)
            total_seconds = await self.repository.get_total_listening_time(guild_id)
            stats_30d = await self.repository.get_listening_stats(guild_id, days=30)

            embed = discord.Embed(
                title="📊 Статистика прослуховування",
                color=consts.COLOR_EMBED_NORMAL
            )

            # Загальна статистика
            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60
            time_str = f"{hours}г {minutes}хв" if hours > 0 else f"{minutes}хв"
            
            embed.add_field(
                name="📈 Загалом",
                value=f"⏱️ Загальний час: **{time_str}**",
                inline=False
            )

            # 30-денна статистика
            s = stats_30d
            embed.add_field(
                name="📅 За 30 днів",
                value=(
                    f"🎵 Треків: **{s['total_tracks']}**\n"
                    f"🆕 Унікальних: **{s['unique_tracks']}**\n"
                    f"⏱️ Час: **{format_duration(s['total_seconds'])}**"
                ),
                inline=False
            )

            # Топ треки
            if top_tracks:
                top_text = "\n".join([
                    f"`{i+1}.` **{t['title'][:40]}** — {t['play_count']}x"
                    for i, t in enumerate(top_tracks)
                ])
                embed.add_field(name="🏆 Топ треки", value=top_text, inline=False)
            else:
                embed.add_field(name="🏆 Топ треки", value="Поки немає даних", inline=False)

            await interaction.followup.send(embed=embed, view=DismissView(), ephemeral=True)
        except Exception as e:
            self.logger.error(f"Stats error: {e}", exc_info=True)
            await interaction.followup.send("❌ Помилка отримання статистики.", ephemeral=True)

    @app_commands.command(name="history", description="Історія прослуховувань")
    @app_commands.describe(query="Пошук в історії (опціонально)")
    async def history(self, interaction: discord.Interaction, query: str = None):
        await interaction.response.defer(ephemeral=True)
        guild_id = interaction.guild_id

        try:
            if query:
                tracks = await self.repository.search_history(guild_id, query, limit=20)
                title = f"🔍 Історія: «{query}»"
            else:
                tracks = await self.repository.get_history(guild_id, limit=25)
                title = "📜 Історія прослуховувань"

            embed = discord.Embed(title=title, color=consts.COLOR_EMBED_NORMAL)

            if tracks:
                lines = []
                for i, t in enumerate(tracks, 1):
                    duration = format_duration(t.get('duration'))
                    played = t.get('played_at', '')
                    if played:
                        # Показуємо тільки дату і час
                        played = played[:16].replace('T', ' ')
                    lines.append(f"`{i}.` **{t['title'][:35]}** | `{duration}` | {played}")
                
                # Розбиваємо на chunk-и щоб не перевищити ліміт
                text = "\n".join(lines)
                if len(text) > 1024:
                    text = "\n".join(lines[:15]) + f"\n... та ще {len(lines) - 15}"
                
                embed.add_field(name="🎵 Треки", value=text, inline=False)
                embed.set_footer(text=f"Знайдено: {len(tracks)} трек(ів)")
            else:
                embed.add_field(name="🎵 Треки", value="Історія порожня", inline=False)

            await interaction.followup.send(embed=embed, view=DismissView(), ephemeral=True)
        except Exception as e:
            self.logger.error(f"History error: {e}", exc_info=True)
            await interaction.followup.send("❌ Помилка отримання історії.", ephemeral=True)

async def setup(bot):
    await bot.add_cog(MusicCog(bot))
