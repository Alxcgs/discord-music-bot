import discord
from discord import app_commands
from discord.ext import commands
import asyncio
import logging
from discord_music_bot.services.queue_service import QueueService
from discord_music_bot.services.player_service import PlayerService
import yt_dlp
from discord_music_bot import consts

def format_duration(duration):
    """Форматує тривалість у читабельний формат."""
    if not duration:
        return "∞"
    
    minutes = duration // 60
    seconds = duration % 60
    hours = minutes // 60
    minutes = minutes % 60
    
    if hours > 0:
        return f"{int(hours):02d}:{int(minutes):02d}:{int(seconds):02d}"
    else:
        return f"{int(minutes):02d}:{int(seconds):02d}"

class MusicControls(discord.ui.View):
    def __init__(self, cog, guild, timeout=None):
        super().__init__(timeout=timeout)
        self.cog = cog
        self.guild = guild

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        voice_client = interaction.guild.voice_client
        if not voice_client:
            await interaction.response.send_message("Бот наразі не в голосовому каналі.", ephemeral=True)
            return False
        if not interaction.user.voice or interaction.user.voice.channel != voice_client.channel:
            await interaction.response.send_message("Ви повинні бути в тому ж голосовому каналі, що й бот.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Попередній", style=discord.ButtonStyle.secondary, emoji=consts.EMOJI_PREVIOUS, custom_id="previous")
    async def previous_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild_id = interaction.guild.id
        
        if guild_id in self.cog.processing_buttons:
            await interaction.response.send_message("Зачекайте, обробляється попередня дія.", ephemeral=True)
            return
        
        self.cog.processing_buttons.add(guild_id)
        
        try:
            if not self.cog.track_history.get(guild_id, []):
                await interaction.response.send_message("Немає попередніх треків.", ephemeral=True)
                return
            
            prev_track = self.cog.track_history[guild_id].pop()
            
            if guild_id in self.cog.current_song:
                current = self.cog.current_song[guild_id].copy()
                self.cog.queue_service.push_front(guild_id, current)
            
            self.cog.queue_service.push_front(guild_id, prev_track)
            
            voice_client = interaction.guild.voice_client
            self.cog.player_service.stop(voice_client)
            
            await interaction.response.send_message(
                f"⏮️ Повертаємось до треку: {prev_track.get('title', 'Невідомий трек')}", 
                ephemeral=False
            )
            
        except Exception as e:
            self.cog.logger.error(f"Error in previous_button: {e}", exc_info=True)
            await interaction.response.send_message("❌ Помилка при поверненні до попереднього треку.", ephemeral=True)
        
        finally:
            self.cog.processing_buttons.discard(guild_id)

    @discord.ui.button(label="Пауза", style=discord.ButtonStyle.secondary, emoji=consts.EMOJI_PAUSE, custom_id="pause_resume")
    async def pause_resume_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        voice_client = interaction.guild.voice_client
        if voice_client and voice_client.is_playing():
            voice_client.pause()
            button.label = "Відновити"
            button.emoji = "▶️"
            await interaction.response.edit_message(view=self)
        elif self.cog.player_service.is_paused(voice_client):
            self.cog.player_service.resume(voice_client)
            button.label = "Пауза"
            button.emoji = "⏸️"
            await interaction.response.edit_message(view=self)
        else:
            await interaction.response.send_message("Зараз нічого не грає.", ephemeral=True)

    @discord.ui.button(label="Пропустити", style=discord.ButtonStyle.secondary, emoji=consts.EMOJI_SKIP, custom_id="skip")
    async def skip_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        voice_client = interaction.guild.voice_client
        if voice_client and (voice_client.is_playing() or voice_client.is_paused()):
            voice_client.stop()
            await interaction.response.send_message(f"⏭️ Трек пропущено {interaction.user.mention}.", ephemeral=False)
        else:
            await interaction.response.send_message("Нічого пропускати.", ephemeral=True)

    @discord.ui.button(label="Черга", style=discord.ButtonStyle.secondary, emoji=consts.EMOJI_QUEUE, custom_id="queue")
    async def queue_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = QueueView(self.cog, interaction.guild)
        await interaction.response.send_message(embed=view.create_embed(), view=view, ephemeral=True)

    @discord.ui.button(label="Вийти", style=discord.ButtonStyle.secondary, emoji=consts.EMOJI_LEAVE, custom_id="leave")
    async def leave_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        voice_client = interaction.guild.voice_client
        if voice_client and voice_client.is_connected():
            await self.cog.leave_logic(interaction.guild)
            await interaction.response.send_message(f"👋 Бот вийшов з каналу за командою {interaction.user.mention}.", ephemeral=False)
            self.stop()
        else:
            await interaction.response.send_message("Бот не підключений до голосового каналу.", ephemeral=True)

class QueueView(discord.ui.View):
    def __init__(self, cog, guild, timeout=60):
        super().__init__(timeout=timeout)
        self.cog = cog
        self.guild = guild
        self.current_page = 0
        self.items_per_page = consts.ITEMS_PER_PAGE
        self.queue = self.cog.queue_service.get_queue(guild.id)
        self.total_pages = max((len(self.queue) - 1) // self.items_per_page + 1, 1)
        self.update_buttons()

    def create_embed(self):
        guild_id = self.guild.id
        embed = discord.Embed(title="📄 Черга відтворення", color=consts.COLOR_EMBED_NORMAL)

        if guild_id in self.cog.current_song:
            song_info = self.cog.current_song[guild_id]
            duration_str = format_duration(song_info.get('duration'))
            current_track = f"[{song_info.get('title', 'Невідомий трек')}]({song_info.get('url', '#')}) | `{duration_str}`"
            embed.add_field(
                name="🎶 Зараз грає",
                value=f"{current_track}\nЗамовив користувач: {song_info['requester'].mention}",
                inline=False
            )

        if self.queue:
            start_idx = self.current_page * self.items_per_page
            end_idx = min(start_idx + self.items_per_page, len(self.queue))
            queue_text = []
            
            for i, item in enumerate(self.queue[start_idx:end_idx], start=start_idx + 1):
                title = item.get('title', 'Завантаження...')
                url = item.get('webpage_url', '#')
                duration_str = format_duration(item.get('duration', 0))
                track_text = f"`{i}.` [{title}]({url}) | `{duration_str}`"
                queue_text.append(track_text)

            if queue_text:
                chunks = []
                current_chunk = []
                current_length = 0
                for track in queue_text:
                    if current_length + len(track) > 1000:
                        if current_chunk: chunks.append("\n".join(current_chunk))
                        current_chunk = [track]
                        current_length = len(track)
                    else:
                        current_chunk.append(track)
                        current_length += len(track) + 1
                if current_chunk: chunks.append("\n".join(current_chunk))
                
                for i, chunk in enumerate(chunks):
                    field_name = "📑 Треки в черзі" if i == 0 else "\u200b"
                    embed.add_field(name=field_name, value=chunk, inline=False)

            total_duration = sum(item.get('duration', 0) for item in self.queue)
            embed.set_footer(text=f"Всього треків: {len(self.queue)} | Загальна тривалість: {format_duration(total_duration)} | Сторінка {self.current_page + 1}/{self.total_pages}")
        else:
            embed.add_field(name="📑 Треки в черзі", value="Черга порожня", inline=False)

        return embed

    def update_buttons(self):
        self.clear_items()
        first_button = discord.ui.Button(style=discord.ButtonStyle.secondary, emoji=consts.EMOJI_FIRST_PAGE, custom_id="first", disabled=self.current_page == 0)
        first_button.callback = self.first_page
        self.add_item(first_button)

        prev_button = discord.ui.Button(style=discord.ButtonStyle.secondary, emoji=consts.EMOJI_PREV_PAGE, custom_id="prev", disabled=self.current_page == 0)
        prev_button.callback = self.prev_page
        self.add_item(prev_button)

        next_button = discord.ui.Button(style=discord.ButtonStyle.secondary, emoji=consts.EMOJI_NEXT_PAGE, custom_id="next", disabled=self.current_page >= self.total_pages - 1)
        next_button.callback = self.next_page
        self.add_item(next_button)

        last_button = discord.ui.Button(style=discord.ButtonStyle.secondary, emoji=consts.EMOJI_LAST_PAGE, custom_id="last", disabled=self.current_page >= self.total_pages - 1)
        last_button.callback = self.last_page
        self.add_item(last_button)
        
        refresh_button = discord.ui.Button(style=discord.ButtonStyle.secondary, emoji=consts.EMOJI_REFRESH, custom_id="refresh")
        refresh_button.callback = self.refresh_page
        self.add_item(refresh_button)

    async def _handle_page_change(self, interaction: discord.Interaction, new_page):
        self.current_page = new_page
        self.queue = self.cog.queue_service.get_queue(self.guild.id) # Update local queue ref
        self.update_buttons()
        await interaction.response.edit_message(embed=self.create_embed(), view=self)

    async def first_page(self, interaction): await self._handle_page_change(interaction, 0)
    async def prev_page(self, interaction): await self._handle_page_change(interaction, max(0, self.current_page - 1))
    async def next_page(self, interaction): await self._handle_page_change(interaction, min(self.total_pages - 1, self.current_page + 1))
    async def last_page(self, interaction): await self._handle_page_change(interaction, self.total_pages - 1)
    async def refresh_page(self, interaction): await self._handle_page_change(interaction, self.current_page)


class SearchResultsView(discord.ui.View):
    def __init__(self, cog, user, results, timeout=60):
        super().__init__(timeout=timeout)
        self.cog = cog
        self.user = user
        self.results = results
        self.current_page = 0
        self.items_per_page = consts.SEARCH_ITEMS_PER_PAGE
        self.total_pages = (len(results) - 1) // self.items_per_page + 1
        self.selected_track = None
        self.update_buttons()

    def update_buttons(self):
        self.clear_items()
        start_idx = self.current_page * self.items_per_page
        end_idx = min(start_idx + self.items_per_page, len(self.results))
        
        for i in range(start_idx, end_idx):
            button = discord.ui.Button(style=discord.ButtonStyle.secondary, label=str(i - start_idx + 1), custom_id=f"select_{i}")
            button.callback = self.create_select_callback(i)
            self.add_item(button)
        
        if self.total_pages > 1:
            if self.current_page > 0:
                prev = discord.ui.Button(style=discord.ButtonStyle.primary, emoji=consts.EMOJI_LEFT_ARROW, custom_id="prev_page")
                prev.callback = self.prev_page
                self.add_item(prev)
            if self.current_page < self.total_pages - 1:
                next_btn = discord.ui.Button(style=discord.ButtonStyle.primary, emoji=consts.EMOJI_RIGHT_ARROW, custom_id="next_page")
                next_btn.callback = self.next_page
                self.add_item(next_btn)
                
        cancel = discord.ui.Button(style=discord.ButtonStyle.danger, emoji=consts.EMOJI_CANCEL, custom_id="cancel")
        cancel.callback = self.cancel
        self.add_item(cancel)

    def create_select_callback(self, index):
        async def callback(interaction: discord.Interaction):
            if interaction.user != self.user:
                await interaction.response.send_message("Ви не можете використовувати це меню.", ephemeral=True)
                return
            self.selected_track = self.results[index]
            self.stop()
            await interaction.message.delete()
        return callback

    async def prev_page(self, interaction: discord.Interaction):
        if interaction.user != self.user: return
        self.current_page = max(0, self.current_page - 1)
        await self.update_message(interaction)

    async def next_page(self, interaction: discord.Interaction):
        if interaction.user != self.user: return
        self.current_page = min(self.total_pages - 1, self.current_page + 1)
        await self.update_message(interaction)

    async def cancel(self, interaction: discord.Interaction):
        if interaction.user != self.user: return
        self.selected_track = None
        self.stop()
        await interaction.message.delete()

    async def update_message(self, interaction):
        self.update_buttons()
        await interaction.response.edit_message(embed=self.create_embed(), view=self)

    def create_embed(self):
        embed = discord.Embed(title="🔍 Результати пошуку", color=consts.COLOR_EMBED_PLAYING)
        start_idx = self.current_page * self.items_per_page
        end_idx = min(start_idx + self.items_per_page, len(self.results))
        
        for i, track in enumerate(self.results[start_idx:end_idx], start=1):
            duration = format_duration(track.get('duration', 0))
            embed.add_field(name=f"{i}. {track.get('title', '...')}", value=f"⏱️ {duration}\n🔗 [Link]({track.get('webpage_url')})", inline=False)
        
        if self.total_pages > 1: embed.set_footer(text=f"Сторінка {self.current_page + 1}/{self.total_pages}")
        return embed

class MusicCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.queue_service = QueueService()
        self.player_service = PlayerService()
        self.current_song = {}
        self.control_messages = {}
        self.player_channels = {}
        self.track_history = {}
        self.processing_buttons = set()
        self.logger = logging.getLogger('MusicBot')
        self.logger.setLevel(logging.INFO)
        
        self.light_ydl_opts = consts.YTDL_OPTIONS_LIGHT
        self.preload_next = True

    async def get_video_info(self, url):
        search_url = url if any(x in url.lower() for x in ['youtube.com', 'youtu.be', 'soundcloud.com']) else f"ytsearch:{url}"
        with yt_dlp.YoutubeDL(self.light_ydl_opts) as ydl:
            try:
                info = await self.bot.loop.run_in_executor(None, lambda: ydl.extract_info(search_url, download=False))
                if not info: return None
                if 'entries' in info: info = info['entries'][0]
                return {
                    'title': info.get('title', 'Unknown'),
                    'url': info.get('webpage_url', url) or info.get('url', url),
                    'duration': info.get('duration'),
                    'thumbnail': info.get('thumbnail')
                }
            except Exception as e:
                self.logger.error(f"Error extracting info: {e}")
                return None

    async def update_player(self, guild, channel):
        try:
            guild_id = guild.id
            embed = discord.Embed(title="🎵 Музичний плеєр", color=consts.COLOR_EMBED_PLAYING)
            
            if guild_id in self.current_song:
                song = self.current_song[guild_id]
                embed.add_field(name="🎶 Зараз грає", value=f"[{song['title']}]({song['url']})\n👤 {song['requester'].mention}", inline=False)
                if song.get('thumbnail'): embed.set_thumbnail(url=song['thumbnail'])
            else:
                embed.add_field(name="🎶 Зараз грає", value="Нічого не грає", inline=False)

            queue = self.queue_service.get_queue(guild_id)
            q_text = "\n".join([f"`{i+1}.` {t['title']}" for i, t in enumerate(queue[:5])]) or "Черга порожня"
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

    async def play_next_song(self, guild, voice_client):
        try:
            guild_id = guild.id
            if guild_id in self.current_song:
                # Add to history
                if guild_id not in self.track_history: self.track_history[guild_id] = []
                self.track_history[guild_id].append(self.current_song[guild_id])
            
            queue = self.queue_service.get_queue(guild_id)
            if queue:
                item = self.queue_service.get_next_track(guild_id)
                player = await self.player_service.play_stream(
                    voice_client, 
                    item['url'], 
                    self.bot.loop, 
                    lambda e: self.bot.loop.create_task(self.check_after_play(guild, voice_client, e))
                )
                
                self.current_song[guild_id] = {
                    'title': player.title, 'url': player.url, 'thumbnail': player.thumbnail,
                    'duration': player.duration, 'requester': item['requester'], 'player': player
                }
                
                if guild_id in self.player_channels:
                    channel = self.bot.get_channel(self.player_channels[guild_id])
                    if channel: await self.update_player(guild, channel)
            else:
                if guild_id in self.current_song: del self.current_song[guild_id]
                if guild_id in self.player_channels:
                    channel = self.bot.get_channel(self.player_channels[guild_id])
                    if channel: await self.update_player(guild, channel)
                await asyncio.sleep(60)
                if not self.player_service.is_playing(voice_client) and not self.queue_service.get_queue(guild_id):
                    await voice_client.disconnect()
        except Exception as e:
            self.logger.error(f"Play next error: {e}")

    async def check_after_play(self, guild, voice_client, error):
        if voice_client.is_connected():
            await self.play_next_song(guild, voice_client)

    async def leave_logic(self, guild):
        voice_client = guild.voice_client
        if voice_client:
            self.queue_service.clear(guild.id)
            if guild.id in self.current_song: del self.current_song[guild.id]
            await voice_client.disconnect()

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if member.id == self.bot.user.id and after.channel is None:
            # Bot disconnected
            pass

    @app_commands.command(name="join", description="Підключити бота до голосового каналу")
    async def join(self, interaction: discord.Interaction):
        if not interaction.user.voice:
            await interaction.response.send_message("Ви не в голосовому каналі!", ephemeral=True)
            return
        
        channel = interaction.user.voice.channel
        voice_client = interaction.guild.voice_client

        if voice_client and voice_client.is_connected():
            if voice_client.channel != channel:
                await voice_client.move_to(channel)
                await interaction.response.send_message(f"Перемістився до {channel.mention}")
            else:
                await interaction.response.send_message("Я вже тут!", ephemeral=True)
        else:
            await channel.connect()
            await interaction.response.send_message(f"Приєднався до {channel.mention}")

    @app_commands.command(name="play", description="Відтворити музику (URL або пошук)")
    @app_commands.describe(query="Посилання або назва пісні")
    async def play(self, interaction: discord.Interaction, query: str):
        if not interaction.user.voice:
            await interaction.response.send_message("Зайдіть у голосовий канал!", ephemeral=True)
            return

        await interaction.response.defer()
        
        voice_client = interaction.guild.voice_client
        if not voice_client:
            voice_client = await interaction.user.voice.channel.connect()

        # Check for playlist
        if 'list=' in query or '/sets/' in query:
             await interaction.followup.send("Плейлисти поки мають обмежену підтримку у Slash. Спробуйте посилання на трек.")
             # Simplified for now to avoid copying the massive process_playlist logic logic blindly
             # If needed, can be ported similarly.
             return

        info = await self.get_video_info(query)
        if not info:
            await interaction.followup.send("❌ Не вдалося знайти трек.")
            return

        guild_id = interaction.guild.id
        
        info['requester'] = interaction.user
        self.queue_service.add_track(guild_id, info)
        
        await interaction.followup.send(f"✅ Додано: **{info['title']}**")
        
        await self.update_player(interaction.guild, interaction.channel)
        
        if not self.player_service.is_playing(voice_client) and not self.player_service.is_paused(voice_client):
            await self.play_next_song(interaction.guild, voice_client)

    @app_commands.command(name="skip", description="Пропустити трек")
    async def skip(self, interaction: discord.Interaction):
        voice_client = interaction.guild.voice_client
        if voice_client and (self.player_service.is_playing(voice_client) or self.player_service.is_paused(voice_client)):
            self.player_service.stop(voice_client)
            await interaction.response.send_message("⏭️ Пропущено.")
        else:
            await interaction.response.send_message("Нічого не грає.", ephemeral=True)

    @app_commands.command(name="pause", description="Пауза")
    async def pause(self, interaction: discord.Interaction):
        voice_client = interaction.guild.voice_client
        if self.player_service.is_playing(voice_client):
            self.player_service.pause(voice_client)
            await interaction.response.send_message("⏸️ Пауза.")
        else:
            await interaction.response.send_message("Неможливо поставити на паузу.", ephemeral=True)

    @app_commands.command(name="resume", description="Продовжити")
    async def resume(self, interaction: discord.Interaction):
        voice_client = interaction.guild.voice_client
        if self.player_service.is_paused(voice_client):
            self.player_service.resume(voice_client)
            await interaction.response.send_message("▶️ Продовжуємо.")
        else:
            await interaction.response.send_message("Немає чого продовжувати.", ephemeral=True)

    @app_commands.command(name="stop", description="Зупинити та очистити")
    async def stop(self, interaction: discord.Interaction):
        voice_client = interaction.guild.voice_client
        if voice_client:
            self.queue_service.clear(interaction.guild.id)
            self.player_service.stop(voice_client)
            await self.update_player(interaction.guild, interaction.channel)
            await interaction.response.send_message("⏹️ Зупинено.")
        else:
            await interaction.response.send_message("Я не граю.", ephemeral=True)

    @app_commands.command(name="queue", description="Показати чергу")
    async def queue(self, interaction: discord.Interaction):
        view = QueueView(self, interaction.guild)
        await interaction.response.send_message(embed=view.create_embed(), view=view)

    @app_commands.command(name="leave", description="Вигнати бота")
    async def leave(self, interaction: discord.Interaction):
        await self.leave_logic(interaction.guild)
        await interaction.response.send_message("👋 Бувай!")

async def setup(bot):
    await bot.add_cog(MusicCog(bot))
