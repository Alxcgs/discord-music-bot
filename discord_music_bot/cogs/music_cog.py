import discord
from discord.ext import commands
import asyncio
import logging
from discord_music_bot.audio_source import YTDLSource
from discord_music_bot.utils import format_duration
import yt_dlp

# Словники для зберігання стану музики для кожного сервера (краще інкапсулювати в Cog)
music_queues = {}
current_song = {}

# --- Клас для кнопок керування ---
class MusicControls(discord.ui.View):
    def __init__(self, ctx, cog, timeout=None):
        super().__init__(timeout=timeout)
        self.ctx = ctx
        self.cog = cog

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not self.ctx.voice_client:
            await interaction.response.send_message("Бот наразі не в голосовому каналі.", ephemeral=True)
            return False
        if not interaction.user.voice or interaction.user.voice.channel != self.ctx.voice_client.channel:
            await interaction.response.send_message("Ви повинні бути в тому ж голосовому каналі, що й бот.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Попередній", style=discord.ButtonStyle.secondary, emoji="⏮️", custom_id="previous")
    async def previous_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild_id = self.ctx.guild.id
        
        if guild_id in self.cog.processing_buttons:
            await interaction.response.send_message("Зачекайте, обробляється попередня дія.", ephemeral=True)
            return
        
        self.cog.processing_buttons.add(guild_id)
        
        try:
            # Перевіряємо наявність історії треків
            if not self.cog.track_history.get(guild_id, []):
                self.cog.logger.warning(f"No track history for guild {guild_id}")
                await interaction.response.send_message("Немає попередніх треків.", ephemeral=True)
                return
            
            self.cog.logger.info(f"Track history for guild {guild_id}: {len(self.cog.track_history[guild_id])} tracks")
            
            # Отримуємо останній трек з історії
            prev_track = self.cog.track_history[guild_id].pop()
            self.cog.logger.info(f"Retrieved previous track: {prev_track.get('title')}")
            
            # Зберігаємо поточний трек в чергу, якщо він є
            if guild_id in self.cog.current_song:
                current = self.cog.current_song[guild_id].copy()
                if guild_id not in self.cog.music_queues:
                    self.cog.music_queues[guild_id] = []
                self.cog.music_queues[guild_id].insert(0, current)
                self.cog.logger.info(f"Saved current track to queue: {current.get('title')}")
            
            # Додаємо попередній трек на початок черги
            if guild_id not in self.cog.music_queues:
                self.cog.music_queues[guild_id] = []
            self.cog.music_queues[guild_id].insert(0, prev_track)
            self.cog.logger.info(f"Added previous track to queue: {prev_track.get('title')}")
            
            # Зупиняємо поточний трек (це викличе play_next_song)
            voice_client = self.ctx.voice_client
            if voice_client and (voice_client.is_playing() or voice_client.is_paused()):
                voice_client.stop()
                self.cog.logger.info("Stopped current track")
            
            await interaction.response.send_message(
                f"⏮️ Повертаємось до треку: {prev_track.get('title', 'Невідомий трек')}", 
                ephemeral=False
            )
            
        except Exception as e:
            self.cog.logger.error(f"Error in previous_button: {e}", exc_info=True)
            await interaction.response.send_message("❌ Помилка при поверненні до попереднього треку.", ephemeral=True)
        
        finally:
            self.cog.processing_buttons.discard(guild_id)

    @discord.ui.button(label="Пауза", style=discord.ButtonStyle.secondary, emoji="⏸️", custom_id="pause_resume")
    async def pause_resume_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild_id = self.ctx.guild.id
        
        if guild_id in self.cog.processing_buttons:
            await interaction.response.send_message("Зачекайте, обробляється попередня дія.", ephemeral=True)
            return
        
        self.cog.processing_buttons.add(guild_id)
        
        try:
            voice_client = self.ctx.voice_client
            if voice_client and voice_client.is_playing():
                voice_client.pause()
                button.label = "Відновити"
                button.emoji = "▶️"
                await interaction.response.edit_message(view=self)
            elif voice_client and voice_client.is_paused():
                voice_client.resume()
                button.label = "Пауза"
                button.emoji = "⏸️"
                await interaction.response.edit_message(view=self)
            else:
                await interaction.response.send_message("Зараз нічого не грає.", ephemeral=True)
        finally:
            self.cog.processing_buttons.discard(guild_id)

    @discord.ui.button(label="Пропустити", style=discord.ButtonStyle.primary, emoji="⏭️", custom_id="skip")
    async def skip_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        voice_client = self.ctx.voice_client
        if voice_client and (voice_client.is_playing() or voice_client.is_paused()):
            voice_client.stop()
            await interaction.response.send_message(f"⏭️ Трек пропущено {interaction.user.mention}.", ephemeral=False)
        else:
            await interaction.response.send_message("Нічого пропускати.", ephemeral=True)

    @discord.ui.button(label="Черга", style=discord.ButtonStyle.secondary, emoji="📄", custom_id="queue")
    async def queue_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        command = self.cog.bot.get_command('queue')
        if command:
            await interaction.response.defer(ephemeral=True)
            await self.cog.queue(self.ctx)
            await interaction.followup.send("Показано чергу.", ephemeral=True)
        else:
            await interaction.response.send_message("Команда !queue не знайдена.", ephemeral=True)

    @discord.ui.button(label="Вийти", style=discord.ButtonStyle.danger, emoji="🚪", custom_id="leave")
    async def leave_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        voice_client = self.ctx.voice_client
        if voice_client and voice_client.is_connected():
            await self.cog.leave_logic(self.ctx)
            await interaction.response.send_message(f"👋 Бот вийшов з каналу за командою {interaction.user.mention}.", ephemeral=False)
            self.stop()
        else:
            await interaction.response.send_message("Бот не підключений до голосового каналу.", ephemeral=True)


class MusicCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.music_queues = {}
        self.current_song = {}
        self.control_messages = {}
        self.player_channels = {}
        self.track_history = {}  # Історія треків для кожного сервера
        self.processing_buttons = set()  # Для запобігання подвійних натискань
        self.logger = logging.getLogger('MusicBot')
        self.logger.setLevel(logging.INFO)
        
        # Оптимізовані налаштування для швидкого завантаження
        self.light_ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': True,
            'skip_download': True,
            'force_generic_extractor': False,
            'format': 'bestaudio[acodec=opus][abr<=128]/bestaudio/best',  # Зменшений бітрейт для швидшого завантаження
            'format_sort': ['abr', 'asr', 'ext'],
            'cachedir': False,
            'default_search': 'ytsearch',
            'source_address': '0.0.0.0',
            'nocheckcertificate': True,
            'ignoreerrors': True,
            'retries': 3,
            'socket_timeout': 5,  # Зменшений таймаут
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            },
            'buffersize': 32*1024,  # Збільшений буфер
            'concurrent_fragment_downloads': 5,  # Більше паралельних завантажень
            'postprocessors': [{  # Оптимізація аудіо
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'opus',
                'preferredquality': '128'
            }]
        }
        
        # Налаштування для завантаження плейлистів
        self.playlist_opts = {
            **self.light_ydl_opts,
            'extract_flat': 'in_playlist',
            'playlistend': 50  # Обмеження кількості треків для безпеки
        }
        
        self.preload_next = True
        self.preloaded_tracks = {}

    async def preload_next_track(self, ctx, url):
        """Попереднє завантаження наступного треку."""
        try:
            guild_id = ctx.guild.id
            self.logger.info(f"Preloading next track: {url}")
            player = await YTDLSource.from_url(url, loop=self.bot.loop, stream=True)
            if player:
                self.preloaded_tracks[guild_id] = player
                self.logger.info(f"Successfully preloaded: {player.title}")
        except Exception as e:
            self.logger.error(f"Error preloading track: {e}")
            self.preloaded_tracks.pop(guild_id, None)

    async def get_video_info(self, url):
        """Оптимізоване отримання інформації про відео з кешуванням."""
        max_retries = 3
        retry_count = 0
        
        while retry_count < max_retries:
            try:
                if not ('youtube.com' in url or 'youtu.be' in url):
                    search_url = f"ytsearch:{url}"
                else:
                    search_url = url
                
                self.logger.info(f"Extracting info for: {search_url} (attempt {retry_count + 1}/{max_retries})")
                
                with yt_dlp.YoutubeDL(self.light_ydl_opts) as ydl:
                    try:
                        info = await self.bot.loop.run_in_executor(
                            None, 
                            lambda: ydl.extract_info(search_url, download=False)
                        )
                        
                        if not info:
                            self.logger.warning(f"No info extracted for: {search_url}")
                            retry_count += 1
                            if retry_count < max_retries:
                                await asyncio.sleep(1)
                                continue
                            return None
                            
                        if 'entries' in info:
                            if not info['entries']:
                                self.logger.warning("No entries found in search results")
                                return None
                            info = info['entries'][0]
                        
                        self.logger.info(f"Successfully extracted info for: {info.get('title', 'Unknown')}")
                        
                        return {
                            'title': info.get('title', 'Невідома назва'),
                            'url': info.get('webpage_url', url) or info.get('url', url),
                            'duration': info.get('duration'),
                            'thumbnail': info.get('thumbnail'),
                            'format': info.get('format_id', 'best')  # Зберігаємо формат для оптимізації
                        }
                    except Exception as e:
                        self.logger.error(f"Error extracting video info: {str(e)}", exc_info=True)
                        retry_count += 1
                        if retry_count < max_retries:
                            await asyncio.sleep(1)
                            continue
                        return None
            except Exception as e:
                self.logger.error(f"Error in get_video_info: {str(e)}", exc_info=True)
                retry_count += 1
                if retry_count < max_retries:
                    await asyncio.sleep(1)
                    continue
                return None
        return None

    async def update_player(self, ctx, force_new=False):
        """Оновлює або створює нове повідомлення плеєра."""
        try:
            guild_id = ctx.guild.id
            
            embed = discord.Embed(
                title="🎵 Музичний плеєр",
                color=discord.Color.blue()
            )
            
            if guild_id in self.current_song:
                song_info = self.current_song[guild_id]
                duration_str = format_duration(song_info.get('duration'))
                embed.add_field(
                    name="🎶 Зараз грає",
                    value=f"[{song_info.get('title', 'Невідомий трек')}]({song_info.get('url', '#')})\n"
                          f"Тривалість: `{duration_str}`\n"
                          f"Замовив користувач: {song_info['requester'].mention}",
                    inline=False
                )
                if song_info.get('thumbnail'):
                    embed.set_thumbnail(url=song_info['thumbnail'])
            else:
                embed.add_field(name="🎶 Зараз грає", value="Нічого не грає", inline=False)

            queue = self.music_queues.get(guild_id, [])
            if queue:
                next_up = []
                for i, item in enumerate(queue[:5]):
                    title = item.get('title', 'Невідома назва')
                    url = item.get('url', '#')
                    next_up.append(f"`{i+1}.` [{title}]({url}) (Замовив користувач: {item['requester'].mention})")
                queue_text = "\n".join(next_up)
                if len(queue) > 5:
                    queue_text += f"\n\n... та ще {len(queue) - 5} треків"
            else:
                queue_text = "Черга порожня"
            
            embed.add_field(name="📑 Наступні треки", value=queue_text, inline=False)
            embed.add_field(
                name="ℹ️ Команди",
                value="`.play` - додати трек\n`.skip` - пропустити\n`.queue` - показати чергу\n`.stop` - зупинити",
                inline=False
            )

            view = MusicControls(ctx, self)
            
            try:
                if guild_id in self.control_messages:
                    try:
                        old_msg = await ctx.fetch_message(self.control_messages[guild_id])
                        await old_msg.delete()
                    except (discord.NotFound, discord.Forbidden) as e:
                        self.logger.debug(f"Could not delete old message: {e}")
                    except Exception as e:
                        self.logger.error(f"Error deleting old message: {e}", exc_info=True)

                new_msg = await ctx.send(embed=embed, view=view)
                self.control_messages[guild_id] = new_msg.id
                self.player_channels[guild_id] = ctx.channel.id

            except Exception as e:
                self.logger.error(f"Error sending player message: {e}", exc_info=True)
                raise

        except Exception as e:
            self.logger.error(f"Error updating player: {e}", exc_info=True)
            await ctx.send("❌ Помилка оновлення плеєра. Спробуйте ще раз.")

    async def add_to_history(self, guild_id, track_info):
        """Додає трек до історії."""
        if not track_info:
            return
            
        if guild_id not in self.track_history:
            self.track_history[guild_id] = []
        
        # Створюємо копію треку для історії
        track_copy = {
            'title': track_info.get('title', 'Невідомий трек'),
            'url': track_info.get('url'),
            'webpage_url': track_info.get('webpage_url'),
            'duration': track_info.get('duration'),
            'thumbnail': track_info.get('thumbnail'),
            'requester': track_info.get('requester')
        }
        
        # Додаємо в історію, якщо трек відрізняється від останнього
        if not self.track_history[guild_id] or \
           self.track_history[guild_id][-1].get('url') != track_copy.get('url'):
            self.track_history[guild_id].append(track_copy)
            self.logger.info(f"Added track to history: {track_copy.get('title')} for guild {guild_id}")
            
            # Обмежуємо історію до 50 треків
            if len(self.track_history[guild_id]) > 50:
                self.track_history[guild_id].pop(0)

    async def play_next_song(self, ctx):
        """Оптимізоване відтворення наступної пісні."""
        try:
            guild_id = ctx.guild.id
            
            # Зберігаємо поточний трек в історію перед переходом до наступного
            if guild_id in self.current_song:
                await self.add_to_history(guild_id, self.current_song[guild_id])
            
            if guild_id in self.music_queues and self.music_queues[guild_id]:
                voice_client = ctx.voice_client
                if voice_client and not voice_client.is_playing():
                    source_info = self.music_queues[guild_id].pop(0)
                    url = source_info.get('webpage_url') or source_info['url']
                    
                    self.logger.info(f"Playing next song: {source_info.get('title', url)}")
                    
                    try:
                        player = await YTDLSource.from_url(url, loop=self.bot.loop, stream=True)
                        if player:
                            self.current_song[guild_id] = {
                                'title': player.title,
                                'url': player.url,
                                'webpage_url': url,
                                'thumbnail': player.thumbnail,
                                'duration': player.duration,
                                'requester': source_info['requester'],
                                'player': player
                            }
                            
                            voice_client.play(
                                player, 
                                after=lambda e: self.bot.loop.create_task(self.check_after_play(ctx, e))
                            )
                            await self.update_player(ctx)
                        else:
                            await ctx.send("❌ Не вдалося відтворити трек. Пропускаю...")
                            await self.play_next_song(ctx)
                    except Exception as e:
                        self.logger.error(f"Error creating player: {e}")
                        await ctx.send(f"❌ Помилка відтворення: {source_info.get('title', 'Невідомий трек')}")
                        await self.play_next_song(ctx)
            else:
                if guild_id in self.current_song:
                    del self.current_song[guild_id]
                await self.update_player(ctx)
                await self.delayed_disconnect(ctx)
                
        except Exception as e:
            self.logger.error(f"Error in play_next_song: {e}", exc_info=True)
            await ctx.send("❌ Сталася помилка при відтворенні. Спробуйте ще раз.")

    async def check_after_play(self, ctx, error):
        """Перевірка після завершення відтворення треку."""
        try:
            guild_id = ctx.guild.id
            
            if error:
                self.logger.error(f"Playback error: {error}")
            
            # Зберігаємо поточний трек в історію перед видаленням
            if guild_id in self.current_song:
                await self.add_to_history(guild_id, self.current_song[guild_id])
            
            voice_client = ctx.voice_client
            if voice_client and voice_client.is_connected():
                await self.play_next_song(ctx)
            else:
                await self.update_player(ctx)
                
        except Exception as e:
            self.logger.error(f"Error in check_after_play: {e}", exc_info=True)

    async def leave_logic(self, ctx):
        """Логіка виходу бота з голосового каналу."""
        guild_id = ctx.guild.id
        voice_client = discord.utils.get(self.bot.voice_clients, guild=ctx.guild)

        if voice_client and voice_client.is_connected():
            # Очистка стану
            if guild_id in self.music_queues:
                self.music_queues[guild_id].clear()
            if guild_id in self.current_song:
                del self.current_song[guild_id]
            # Видалення повідомлення з кнопками
            if guild_id in self.control_messages:
                try:
                    msg = await ctx.fetch_message(self.control_messages[guild_id])
                    await msg.delete()
                except (discord.NotFound, discord.Forbidden):
                    pass
                del self.control_messages[guild_id]

            await voice_client.disconnect()
            return True
        return False

    @commands.command(name='join', help='Підключити бота до вашого голосового каналу.')
    async def join(self, ctx):
        """Підключає бота до голосового каналу користувача."""
        guild_id = ctx.guild.id
        logging.info(f"[{guild_id}] Join command invoked by {ctx.author.name}") # Додано логування
        if not ctx.author.voice:
            await ctx.send(f"{ctx.author.mention}, ви не підключені до голосового каналу!")
            return

        channel = ctx.author.voice.channel
        voice_client = discord.utils.get(self.bot.voice_clients, guild=ctx.guild)

        if voice_client and voice_client.is_connected():
            if voice_client.channel != channel:
                logging.info(f"[{guild_id}] Moving to channel: {channel.name}") # Додано логування
                await voice_client.move_to(channel)
                await ctx.send(f"Перемістився до каналу: **{channel.name}**")
            else:
                logging.info(f"[{guild_id}] Already in channel: {channel.name}") # Додано логування
                await ctx.send(f"Я вже у вашому каналі: **{channel.name}**")
        else:
            try:
                logging.info(f"[{guild_id}] Connecting to channel: {channel.name}") # Додано логування
                await channel.connect()
                logging.info(f"[{guild_id}] Successfully connected to channel: {channel.name}") # Додано логування
                await ctx.send(f"Приєднався до каналу: **{channel.name}**")
            except discord.ClientException as e:
                 logging.error(f"[{guild_id}] Failed to connect to channel {channel.name}: {e}") # Додано логування
                 await ctx.send(f"Не вдалося підключитися: {e}")
            except Exception as e:
                 logging.error(f"[{guild_id}] Unknown error connecting to channel {channel.name}: {e}") # Додано логування
                 await ctx.send("Сталася помилка при спробі підключення.")

    @commands.command(name='leave', aliases=['disconnect'], help='Відключити бота від голосового каналу.')
    async def leave(self, ctx):
        """Відключає бота від голосового каналу."""
        if await self.leave_logic(ctx):
            await ctx.send("👋 Вийшов з голосового каналу.")
        else:
            await ctx.send("Бот не підключений до голосового каналу.")

    async def process_playlist(self, ctx, url):
        """Обробка плейлиста та додавання треків до черги."""
        try:
            message = await ctx.send("⏳ Завантажую плейлист...")
            guild_id = ctx.guild.id
            
            self.logger.info(f"Processing playlist: {url}")
            tracks_added = 0
            
            with yt_dlp.YoutubeDL(self.playlist_opts) as ydl:
                try:
                    # Отримуємо інформацію про плейлист
                    playlist_info = await self.bot.loop.run_in_executor(
                        None,
                        lambda: ydl.extract_info(url, download=False)
                    )
                    
                    if not playlist_info:
                        await message.edit(content="❌ Не вдалося завантажити плейлист.")
                        return 0
                    
                    playlist_title = playlist_info.get('title', 'Невідомий плейлист')
                    entries = playlist_info.get('entries', [])
                    
                    if not entries:
                        await message.edit(content="❌ Плейлист порожній або не вдалося отримати треки.")
                        return 0
                    
                    # Створюємо чергу для сервера, якщо її немає
                    if guild_id not in self.music_queues:
                        self.music_queues[guild_id] = []
                    
                    # Додаємо треки до черги
                    for entry in entries:
                        if not entry:
                            continue
                            
                        track_info = {
                            'title': entry.get('title', 'Невідома назва'),
                            'url': entry.get('url', entry.get('webpage_url', None)),
                            'webpage_url': entry.get('webpage_url', entry.get('url', None)),
                            'duration': entry.get('duration'),
                            'thumbnail': entry.get('thumbnail'),
                            'requester': ctx.author
                        }
                        
                        if track_info['url'] or track_info['webpage_url']:
                            self.music_queues[guild_id].append(track_info)
                            tracks_added += 1
                            
                            # Оновлюємо повідомлення кожні 10 треків
                            if tracks_added % 10 == 0:
                                await message.edit(content=f"⏳ Завантажено {tracks_added} треків з плейлиста...")
                    
                    # Починаємо відтворення, якщо воно ще не почалось
                    voice_client = ctx.voice_client
                    if not voice_client or not voice_client.is_playing():
                        await self.play_next_song(ctx)
                    
                    await message.edit(content=f"✅ Додано {tracks_added} треків з плейлиста: **{playlist_title}**")
                    return tracks_added
                    
                except Exception as e:
                    self.logger.error(f"Error processing playlist: {str(e)}", exc_info=True)
                    await message.edit(content=f"❌ Помилка при завантаженні плейлиста: {str(e)}")
                    return 0
                    
        except Exception as e:
            self.logger.error(f"Error in process_playlist: {str(e)}", exc_info=True)
            await ctx.send("❌ Сталася помилка при обробці плейлиста.")
            return 0

    @commands.command(name='play', aliases=['p'], help='Відтворити пісню або плейлист за URL чи пошуковим запитом.')
    async def play(self, ctx, *, query: str):
        """Оптимізована версія команди відтворення з підтримкою плейлистів."""
        try:
            if not ctx.author.voice:
                await ctx.send(f"{ctx.author.mention}, підключіться до голосового каналу спочатку!")
                return

            # Підключаємося до голосового каналу
            voice_client = ctx.voice_client
            if not voice_client or not voice_client.is_connected():
                try:
                    voice_client = await ctx.author.voice.channel.connect()
                except Exception as e:
                    self.logger.error(f"Failed to connect to voice channel: {e}")
                    await ctx.send("Не вдалося підключитися до голосового каналу.")
                    return
            elif voice_client.channel != ctx.author.voice.channel:
                try:
                    await voice_client.move_to(ctx.author.voice.channel)
                except Exception as e:
                    self.logger.error(f"Failed to move to voice channel: {e}")
                    await ctx.send("Не вдалося переміститися до вашого каналу.")
                    return

            # Перевіряємо, чи це плейлист
            if 'list=' in query or 'playlist?' in query:
                tracks_added = await self.process_playlist(ctx, query)
                if tracks_added > 0:
                    return
                # Якщо не вдалося обробити як плейлист, продовжуємо як звичайний трек

            # Звичайна обробка одного треку
            await ctx.message.add_reaction('⏳')
            video_info = await self.get_video_info(query)
            
            if not video_info:
                await ctx.message.remove_reaction('⏳', ctx.guild.me)
                await ctx.message.add_reaction('❌')
                await ctx.send("❌ Не вдалося отримати інформацію про відео.")
                return

            guild_id = ctx.guild.id
            if guild_id not in self.music_queues:
                self.music_queues[guild_id] = []

            queue_item = {
                'url': video_info['url'],
                'requester': ctx.author,
                'title': video_info['title'],
                'webpage_url': video_info['url'],
                'thumbnail': video_info.get('thumbnail'),
                'duration': video_info.get('duration')
            }
            
            self.music_queues[guild_id].append(queue_item)
            await ctx.message.remove_reaction('⏳', ctx.guild.me)
            await ctx.message.add_reaction('✅')
            
            await self.update_player(ctx)
            
            if not voice_client.is_playing() and not voice_client.is_paused():
                await self.play_next_song(ctx)

        except Exception as e:
            self.logger.error(f"Error in play command: {e}", exc_info=True)
            await ctx.send(f"❌ Сталася помилка: {str(e)}")
            try:
                await ctx.message.remove_reaction('⏳', ctx.guild.me)
                await ctx.message.add_reaction('❌')
            except:
                pass

    @commands.command(name='pause', help='Поставити відтворення на паузу.')
    async def pause(self, ctx):
        """Ставить музику на паузу."""
        voice_client = discord.utils.get(self.bot.voice_clients, guild=ctx.guild)
        if voice_client and voice_client.is_playing():
            voice_client.pause()
            await ctx.send("⏸️ Відтворення на паузі.")
        else:
            await ctx.send("Зараз нічого не грає або вже на паузі.")

    @commands.command(name='resume', help='Відновити відтворення.')
    async def resume(self, ctx):
        """Відновлює відтворення музики."""
        voice_client = discord.utils.get(self.bot.voice_clients, guild=ctx.guild)
        if voice_client and voice_client.is_paused():
            voice_client.resume()
            await ctx.send("▶️ Відтворення відновлено.")
        else:
            await ctx.send("Нічого відновлювати або музика вже грає.")

    @commands.command(name='skip', aliases=['s'], help='Пропустити поточний трек.')
    async def skip(self, ctx):
        """Пропускає поточний трек."""
        voice_client = discord.utils.get(self.bot.voice_clients, guild=ctx.guild)
        if voice_client and (voice_client.is_playing() or voice_client.is_paused()):
            voice_client.stop()
            await ctx.message.add_reaction('⏭️')
        else:
            await ctx.send("Нічого пропускати.")

    @commands.command(name='stop', help='Зупинити відтворення та очистити чергу.')
    async def stop(self, ctx):
        """Зупиняє музику та очищає чергу."""
        guild_id = ctx.guild.id
        voice_client = discord.utils.get(self.bot.voice_clients, guild=ctx.guild)

        if voice_client and (voice_client.is_playing() or voice_client.is_paused()):
            self.music_queues[guild_id] = []
            voice_client.stop()
            if guild_id in self.current_song:
                del self.current_song[guild_id]
            
            # Оновлюємо плеєр після зупинки
            await self.update_player(ctx)
            await ctx.message.add_reaction('⏹️')
        else:
            await ctx.send("Нічого зупиняти.")

    @commands.command(name='queue', aliases=['q'], help='Показати чергу відтворення.')
    async def queue(self, ctx):
        """Показує поточну чергу музики."""
        guild_id = ctx.guild.id
        queue = self.music_queues.get(guild_id, [])

        if not queue and guild_id not in self.current_song:
            await ctx.send("Черга порожня!")
            return

        embed = discord.Embed(title="📄 Черга відтворення", color=discord.Color.purple())

        if guild_id in self.current_song:
            song_info = self.current_song[guild_id]
            duration_str = format_duration(song_info.get('duration'))
            embed.add_field(
                name="🎶 Зараз грає",
                value=f"[{song_info.get('title', 'Невідомий трек')}]({song_info.get('url', '#')}) | `{duration_str}` | Замовив користувач: {song_info['requester'].mention}",
                inline=False
            )

        if queue:
            next_up = []
            for i, item in enumerate(queue[:10]):
                title = item.get('title', 'Завантаження...')
                url = item.get('webpage_url', '#')
                next_up.append(f"`{i+1}.` [{title}]({url}) (Замовив корситувач: {item['requester'].mention})")

            if next_up:
                embed.add_field(name="⏭️ Далі в черзі", value="\n".join(next_up), inline=False)

            if len(queue) > 10:
                embed.set_footer(text=f"Ще {len(queue) - 10} треків у черзі...")
        elif guild_id in self.current_song:
            embed.add_field(name="⏭️ Далі в черзі", value="Черга порожня.", inline=False)

        await ctx.send(embed=embed)

    @commands.command(name='nowplaying', aliases=['np'], help='Показати поточний трек.')
    async def nowplaying(self, ctx):
        """Показує інформацію про трек, що зараз грає."""
        guild_id = ctx.guild.id
        if guild_id in self.current_song:
            song_info = self.current_song[guild_id]
            player = song_info['player'] # YTDLSource
            # Потрібно отримати поточну позицію відтворення
            # voice_client = discord.utils.get(self.bot.voice_clients, guild=ctx.guild)
            # current_time = 0
            # if voice_client and voice_client.source:
                 # На жаль, discord.py не надає легкого способу отримати поточний час FFmpegPCMAudio
                 # Можна спробувати відстежувати час самостійно, але це не надійно

            duration_str = format_duration(song_info.get('duration'))
            embed = discord.Embed(
                title="🎶 Зараз грає",
                description=f"[{song_info.get('title', 'Невідомий трек')}]({song_info.get('url', '#')})",
                color=discord.Color.blue()
            )
            if song_info.get('thumbnail'):
                embed.set_thumbnail(url=song_info['thumbnail'])
            embed.add_field(name="Тривалість", value=duration_str, inline=True)
            embed.add_field(name="Замовив користувач", value=song_info['requester'].mention, inline=True)
            # Додати прогрес бар, якщо можливо
            # embed.add_field(name="Прогрес", value=f"`{format_duration(current_time)} / {duration_str}`", inline=False)

            # Оновлюємо кнопки, якщо вони є
            view = None
            if guild_id in self.control_messages:
                try:
                    msg = await ctx.fetch_message(self.control_messages[guild_id])
                    view = MusicControls.from_message(msg, self.bot) # Потрібно адаптувати MusicControls
                    # Або просто створити новий View
                    view = MusicControls(ctx, self)
                    # Оновити стан кнопки паузи/відновлення
                    pause_button = discord.utils.get(view.children, custom_id="pause_resume")
                    voice_client = discord.utils.get(self.bot.voice_clients, guild=ctx.guild)
                    if voice_client and voice_client.is_paused():
                        pause_button.label = "Відновити"
                        pause_button.emoji = "▶️"
                    else:
                        pause_button.label = "Пауза"
                        pause_button.emoji = "⏸️"

                except (discord.NotFound, discord.Forbidden):
                    view = MusicControls(ctx, self) # Створюємо новий, якщо старий недоступний
                    self.control_messages.pop(guild_id, None) # Видаляємо недійсний ID
            else:
                 view = MusicControls(ctx, self) # Створюємо новий, якщо не було

            # Видаляємо старе повідомлення, якщо воно є і ми створюємо нове
            if guild_id in self.control_messages and view:
                 try:
                     old_msg = await ctx.fetch_message(self.control_messages[guild_id])
                     await old_msg.delete()
                 except (discord.NotFound, discord.Forbidden):
                     pass
                 del self.control_messages[guild_id]

            new_msg = await ctx.send(embed=embed, view=view)
            self.control_messages[guild_id] = new_msg.id

        else:
            await ctx.send("Зараз нічого не грає.")

    # Обробник подій для автоматичного виходу
    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        """Обробник подій для автоматичного виходу та оновлення плеєра."""
        if member.id == self.bot.user.id and after.channel is None:
            guild_id = member.guild.id
            if guild_id in self.player_channels:
                try:
                    channel = self.bot.get_channel(self.player_channels[guild_id])
                    ctx = await self.bot.get_context(await channel.fetch_message(self.control_messages[guild_id]))
                    await self.update_player(ctx)
                except:
                    pass
            return

        if before.channel and not after.channel and member.id != self.bot.user.id:
            voice_client = discord.utils.get(self.bot.voice_clients, guild=member.guild)
            if voice_client and voice_client.channel == before.channel:
                if len(voice_client.channel.members) == 1 and voice_client.channel.members[0].id == self.bot.user.id:
                    guild_id = member.guild.id
                    await asyncio.sleep(60)
                    
                    voice_client = discord.utils.get(self.bot.voice_clients, guild=member.guild)
                    if voice_client and voice_client.channel == before.channel and len(voice_client.channel.members) == 1:
                        if guild_id in self.music_queues:
                            self.music_queues[guild_id].clear()
                        if guild_id in self.current_song:
                            del self.current_song[guild_id]
                        
                        # Оновлюємо плеєр перед виходом
                        if guild_id in self.player_channels:
                            try:
                                channel = self.bot.get_channel(self.player_channels[guild_id])
                                ctx = await self.bot.get_context(await channel.fetch_message(self.control_messages[guild_id]))
                                await self.update_player(ctx)
                            except:
                                pass
                        
                        await voice_client.disconnect()

    async def delayed_disconnect(self, ctx):
        """Відкладене відключення від голосового каналу."""
        try:
            await asyncio.sleep(60)
            voice_client = ctx.voice_client
            if voice_client and not voice_client.is_playing() and not self.music_queues.get(ctx.guild.id, []):
                await voice_client.disconnect()
                self.logger.info(f"Disconnected from voice channel in guild {ctx.guild.id}")
                await ctx.send("🎵 Черга порожня. Виходжу з голосового каналу.")
        except Exception as e:
            self.logger.error(f"Error in delayed_disconnect: {e}", exc_info=True)


# Функція для додавання кога до бота (зазвичай викликається в main.py)
async def setup(bot):
    await bot.add_cog(MusicCog(bot))