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
    def __init__(self, ctx, cog, timeout=None): # None - кнопки не зникнуть
        super().__init__(timeout=timeout)
        self.ctx = ctx
        self.cog = cog # Передаємо екземпляр Cog для доступу до його методів/стану

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # Перевірка, чи користувач, що натиснув кнопку, знаходиться в тому ж каналі, що й бот
        if not self.ctx.voice_client:
             await interaction.response.send_message("Бот наразі не в голосовому каналі.", ephemeral=True)
             return False
        if not interaction.user.voice or interaction.user.voice.channel != self.ctx.voice_client.channel:
            await interaction.response.send_message("Ви повинні бути в тому ж голосовому каналі, що й бот, щоб керувати музикою.", ephemeral=True)
            return False
        return True

    # Динамічна кнопка Пауза/Відновити
    @discord.ui.button(label="Пауза", style=discord.ButtonStyle.secondary, emoji="⏸️", custom_id="pause_resume")
    async def pause_resume_button(self, interaction: discord.Interaction, button: discord.ui.Button):
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
            await interaction.response.send_message("Зараз нічого не грає або не на паузі.", ephemeral=True)

    @discord.ui.button(label="Пропустити", style=discord.ButtonStyle.primary, emoji="⏭️", custom_id="skip")
    async def skip_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        voice_client = self.ctx.voice_client
        if voice_client and (voice_client.is_playing() or voice_client.is_paused()):
            voice_client.stop() # Зупинка поточного треку викличе 'after' -> play_next_song
            await interaction.response.send_message(f"⏭️ Трек пропущено {interaction.user.mention}.", ephemeral=False)
            # Оновлюємо вигляд кнопок (наприклад, якщо це був останній трек)
            # Або можна просто видалити повідомлення з кнопками
            # await interaction.message.delete()
        else:
            await interaction.response.send_message("Нічого пропускати.", ephemeral=True)

    @discord.ui.button(label="Черга", style=discord.ButtonStyle.secondary, emoji="📄", custom_id="queue")
    async def queue_button(self, interaction: discord.Interaction, button: discord.ui.Button):
         command = self.cog.bot.get_command('queue')
         if command:
             await interaction.response.defer(ephemeral=True)
             # Створюємо новий контекст з інтеракції, щоб викликати команду
             # Це може бути складно, простіше відправити результат команди queue
             await self.cog.queue(self.ctx) # Викликаємо метод кога
             # Потрібно якось відповісти на інтеракцію, можливо, повідомленням про успіх
             await interaction.followup.send("Показано чергу.", ephemeral=True)
         else:
              await interaction.response.send_message("Команда !queue не знайдена.", ephemeral=True)

    @discord.ui.button(label="Вийти", style=discord.ButtonStyle.danger, emoji="🚪", custom_id="leave")
    async def leave_button(self, interaction: discord.Interaction, button: discord.ui.Button):
         voice_client = self.ctx.voice_client
         if voice_client and voice_client.is_connected():
             await self.cog.leave_logic(self.ctx) # Використовуємо логіку виходу з кога
             await interaction.response.send_message(f"👋 Бот вийшов з каналу за командою {interaction.user.mention}.", ephemeral=False)
             self.stop() # Робимо кнопки неактивними
             # Можна видалити повідомлення з кнопками
             # await interaction.message.delete()
         else:
             await interaction.response.send_message("Бот не підключений до голосового каналу.", ephemeral=True)


class MusicCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.music_queues = {}
        self.current_song = {}
        self.control_messages = {}  # Зберігати ID повідомлень з кнопками
        self.player_channels = {}  # Зберігати ID каналів для плеєра
        # Опції для швидкого отримання інформації про відео
        self.light_ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': True,
            'skip_download': True,
            'force_generic_extractor': False
        }

    async def get_video_info(self, url):
        """Отримує базову інформацію про відео без завантаження."""
        try:
            if not url.startswith('http'):
                url = f"ytsearch:{url}"
            
            with yt_dlp.YoutubeDL(self.light_ydl_opts) as ydl:
                try:
                    info = await self.bot.loop.run_in_executor(None, lambda: ydl.extract_info(url, download=False))
                    if info:
                        if 'entries' in info:
                            info = info['entries'][0]
                        return {
                            'title': info.get('title', 'Невідома назва'),
                            'url': info.get('webpage_url', url),
                            'duration': info.get('duration')
                        }
                except:
                    return None
        except:
            return None
        return None

    async def update_player(self, ctx, force_new=False):
        """Оновлює або створює нове повідомлення плеєра."""
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
                      f"Замовив(ла): {song_info['requester'].mention}",
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
                title = item.get('title', 'Завантаження...')
                url = item.get('url', '#')
                next_up.append(f"`{i+1}.` [{title}]({url}) (Замовив(ла): {item['requester'].mention})")
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
            if not force_new and guild_id in self.control_messages:
                try:
                    message = await ctx.fetch_message(self.control_messages[guild_id])
                    await message.edit(embed=embed, view=view)
                    return
                except (discord.NotFound, discord.Forbidden):
                    pass

            if guild_id in self.control_messages:
                try:
                    old_msg = await ctx.fetch_message(self.control_messages[guild_id])
                    await old_msg.delete()
                except (discord.NotFound, discord.Forbidden):
                    pass

            new_msg = await ctx.send(embed=embed, view=view)
            self.control_messages[guild_id] = new_msg.id
            self.player_channels[guild_id] = ctx.channel.id

        except Exception as e:
            logging.error(f"Error updating player: {e}")

    async def play_next_song(self, ctx):
        """Відтворює наступну пісню в черзі."""
        guild_id = ctx.guild.id
        logging.info(f"[{guild_id}] Entering play_next_song")
        
        if guild_id in self.music_queues and self.music_queues[guild_id]:
            voice_client = discord.utils.get(self.bot.voice_clients, guild=ctx.guild)
            if voice_client and not voice_client.is_playing():
                source_info = self.music_queues[guild_id].pop(0)
                url_or_query = source_info['url']
                requester = source_info['requester']
                
                player = await YTDLSource.from_url(url_or_query, loop=self.bot.loop, stream=True)
                
                if player:
                    self.current_song[guild_id] = {
                        'player': player,
                        'requester': requester,
                        'title': player.title,
                        'url': player.url,
                        'thumbnail': player.thumbnail,
                        'duration': player.duration
                    }
                    
                    try:
                        voice_client.play(player, after=lambda e: self.bot.loop.create_task(self.check_after_play(ctx, e)))
                        # Оновлюємо плеєр після початку відтворення
                        await self.update_player(ctx)
                    except Exception as e:
                        logging.error(f"[{guild_id}] Error starting playback: {e}", exc_info=True)
                        await ctx.send(f"❌ Помилка відтворення: `{e}`. Пробую наступний трек...")
                        await self.play_next_song(ctx)
                        return
                else:
                    await ctx.send(f"❌ Не вдалося завантажити трек: {url_or_query}. Пробую наступний...")
                    await self.play_next_song(ctx)
        else:
            if guild_id in self.current_song:
                del self.current_song[guild_id]
            
            # Оновлюємо плеєр, показуючи що нічого не грає
            await self.update_player(ctx)
            
            # Чекаємо перед виходом
            await asyncio.sleep(60)
            voice_client = discord.utils.get(self.bot.voice_clients, guild=ctx.guild)
            if voice_client and not voice_client.is_playing() and not (guild_id in self.music_queues and self.music_queues[guild_id]):
                await voice_client.disconnect()
                await ctx.send("🎵 Черга порожня. Виходжу з голосового каналу.")

    async def check_after_play(self, ctx, error):
        """Перевірка стану після завершення відтворення треку."""
        guild_id = ctx.guild.id
        
        if error:
            logging.error(f'[{guild_id}] Помилка відтворення: {error}')
            if guild_id in self.current_song:
                del self.current_song[guild_id]
            await self.update_player(ctx)
            return

        if guild_id in self.current_song:
            del self.current_song[guild_id]

        await asyncio.sleep(0.5)
        
        voice_client = discord.utils.get(self.bot.voice_clients, guild=ctx.guild)
        if voice_client and voice_client.is_connected():
            await self.play_next_song(ctx)
        else:
            await self.update_player(ctx)

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

    @commands.command(name='play', aliases=['p'], help='Відтворити пісню за URL або пошуковим запитом.')
    async def play(self, ctx, *, query: str):
        """Додає пісню до черги та починає відтворення."""
        guild_id = ctx.guild.id
        
        if not ctx.author.voice:
            await ctx.send(f"{ctx.author.mention}, підключіться до голосового каналу спочатку!")
            return

        voice_client = discord.utils.get(self.bot.voice_clients, guild=ctx.guild)
        if not voice_client or not voice_client.is_connected():
            await ctx.invoke(self.join)
            voice_client = discord.utils.get(self.bot.voice_clients, guild=ctx.guild)
            if not voice_client:
                await ctx.send("Не вдалося підключитися до голосового каналу.")
                return
        elif voice_client.channel != ctx.author.voice.channel:
            try:
                await voice_client.move_to(ctx.author.voice.channel)
            except Exception as e:
                await ctx.send("Не вдалося переміститися до вашого каналу.")
                return

        if guild_id not in self.music_queues:
            self.music_queues[guild_id] = []

        # Отримуємо інформацію про відео перед додаванням до черги
        video_info = await self.get_video_info(query)
        queue_item = {
            'url': query,
            'requester': ctx.author,
            'title': video_info['title'] if video_info else 'Завантаження...',
            'webpage_url': video_info['url'] if video_info else query
        }
        
        self.music_queues[guild_id].append(queue_item)
        await self.update_player(ctx)
        await ctx.message.add_reaction('✅')

        if not voice_client.is_playing() and not voice_client.is_paused():
            await self.play_next_song(ctx)

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
                value=f"[{song_info.get('title', 'Невідомий трек')}]({song_info.get('url', '#')}) | `{duration_str}` | Замовив(ла): {song_info['requester'].mention}",
                inline=False
            )

        if queue:
            next_up = []
            for i, item in enumerate(queue[:10]):
                title = item.get('title', 'Завантаження...')
                url = item.get('webpage_url', '#')
                next_up.append(f"`{i+1}.` [{title}]({url}) (Замовив(ла): {item['requester'].mention})")

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
            embed.add_field(name="Замовив(ла)", value=song_info['requester'].mention, inline=True)
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


# Функція для додавання кога до бота (зазвичай викликається в main.py)
async def setup(bot):
    await bot.add_cog(MusicCog(bot))