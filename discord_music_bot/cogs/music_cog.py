import discord
from discord.ext import commands
import asyncio
import logging
from discord_music_bot.audio_source import YTDLSource
from discord_music_bot.utils import format_duration

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
        self.control_messages = {} # Зберігати ID повідомлень з кнопками

    async def play_next_song(self, ctx):
        """Відтворює наступну пісню в черзі."""
        guild_id = ctx.guild.id
        logging.info(f"[{guild_id}] Entering play_next_song") # Додано логування
        if guild_id in self.music_queues and self.music_queues[guild_id]:
            voice_client = discord.utils.get(self.bot.voice_clients, guild=ctx.guild)
            if voice_client and not voice_client.is_playing():
                source_info = self.music_queues[guild_id].pop(0)
                url_or_query = source_info['url']
                requester = source_info['requester']
                logging.info(f"[{guild_id}] Attempting to get source for: {url_or_query}") # Додано логування

                player = await YTDLSource.from_url(url_or_query, loop=self.bot.loop, stream=True)

                if player:
                    logging.info(f"[{guild_id}] Successfully got source: {player.title}") # Додано логування
                    self.current_song[guild_id] = {
                        'player': player,
                        'requester': requester,
                        'title': player.title,
                        'url': player.url,
                        'thumbnail': player.thumbnail,
                        'duration': player.duration
                    }
                    logging.info(f"[{guild_id}] Attempting to play source: {player.title}") # Додано логування
                    try:
                        voice_client.play(player, after=lambda e: self.bot.loop.create_task(self.check_after_play(ctx, e)))
                        logging.info(f"[{guild_id}] Successfully started playing: {player.title}") # Додано логування
                    except Exception as e:
                        logging.error(f"[{guild_id}] Error starting playback for {player.title}: {e}", exc_info=True)
                        await ctx.send(f"❌ Сталася помилка під час запуску відтворення: `{e}`. Пробую наступний трек...")
                        # Негайно спробувати наступний трек у разі помилки запуску
                        await self.play_next_song(ctx)
                        return # Вийти, щоб не створювати embed для треку, що не запустився

                    embed = discord.Embed(
                        title="🎶 Зараз грає",
                        description=f"[{player.title}]({player.url})",
                        color=discord.Color.blue()
                    )
                    if player.thumbnail:
                        embed.set_thumbnail(url=player.thumbnail)
                    if player.duration:
                        embed.add_field(name="Тривалість", value=format_duration(player.duration), inline=True)
                    embed.add_field(name="Замовив(ла)", value=requester.mention, inline=True)

                    # Видаляємо старе повідомлення з кнопками, якщо воно є
                    if guild_id in self.control_messages:
                        try:
                            old_msg = await ctx.fetch_message(self.control_messages[guild_id])
                            await old_msg.delete()
                        except discord.NotFound:
                            pass # Повідомлення вже видалено
                        except discord.Forbidden:
                            pass # Немає прав видаляти
                        del self.control_messages[guild_id]

                    # Надсилаємо нове повідомлення з кнопками
                    view = MusicControls(ctx, self)
                    msg = await ctx.send(embed=embed, view=view)
                    self.control_messages[guild_id] = msg.id # Зберігаємо ID нового повідомлення

                else:
                    logging.error(f"[{guild_id}] Failed to get source for: {url_or_query}") # Додано логування
                    await ctx.send(f"❌ Не вдалося завантажити трек: {url_or_query}. Пробую наступний...")
                    await self.play_next_song(ctx)
        else:
            logging.info(f"[{guild_id}] Queue is empty or bot is already playing.") # Додано логування
            if guild_id in self.current_song:
                del self.current_song[guild_id]
            # Видаляємо повідомлення з кнопками, коли черга порожня
            if guild_id in self.control_messages:
                 try:
                     old_msg = await ctx.fetch_message(self.control_messages[guild_id])
                     await old_msg.delete()
                 except (discord.NotFound, discord.Forbidden):
                     pass
                 del self.control_messages[guild_id]

            await asyncio.sleep(60) # Чекаємо перед виходом
            voice_client = discord.utils.get(self.bot.voice_clients, guild=ctx.guild)
            if voice_client and not voice_client.is_playing() and not (guild_id in self.music_queues and self.music_queues[guild_id]):
                logging.info(f"[{guild_id}] Leaving voice channel due to inactivity.") # Додано логування
                await voice_client.disconnect()
                await ctx.send("🎵 Черга порожня. Виходжу з голосового каналу.")
        logging.info(f"[{guild_id}] Exiting play_next_song") # Додано логування

    async def check_after_play(self, ctx, error):
        """Перевірка стану після завершення відтворення треку."""
        guild_id = ctx.guild.id
        logging.info(f"[{guild_id}] Entering check_after_play. Error: {error}") # Додано логування

        voice_client = discord.utils.get(self.bot.voice_clients, guild=ctx.guild)

        if error:
            logging.error(f'[{guild_id}] Помилка під час відтворення: {error}')
            await ctx.send(f"❌ Сталася помилка під час відтворення: `{error}`")
            # Спробуємо зупинити відтворення та очистити стан
            if voice_client and voice_client.is_playing():
                logging.warning(f"[{guild_id}] Зупиняю voice_client через помилку.")
                voice_client.stop()
            if guild_id in self.current_song:
                logging.info(f"[{guild_id}] Очищаю current_song через помилку.")
                del self.current_song[guild_id]
            # Не викликаємо play_next_song одразу після помилки, щоб уникнути циклу
            logging.info(f"[{guild_id}] Не викликаю play_next_song через помилку в after callback.")
            return # Виходимо, щоб не продовжувати відтворення

        # Очистка поточного треку після успішного завершення
        # cleanup() викликається автоматично бібліотекою discord.py перед after callback
        if guild_id in self.current_song:
             logging.info(f"[{guild_id}] Очищаю current_song після успішного відтворення.")
             del self.current_song[guild_id]

        # Невелике очікування перед наступним треком
        await asyncio.sleep(0.5) # Збільшено час очікування

        # Перевіряємо, чи бот всеще підключений перед спробою грати далі
        if voice_client and voice_client.is_connected():
            logging.info(f"[{guild_id}] Викликаю play_next_song з check_after_play.")
            await self.play_next_song(ctx)
        else:
            logging.info(f"[{guild_id}] Не викликаю play_next_song, бот не підключений.")
        logging.info(f"[{guild_id}] Exiting check_after_play.") # Додано логування

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
        logging.info(f"[{guild_id}] Play command invoked by {ctx.author.name} with query: {query}") # Додано логування
        voice_client = discord.utils.get(self.bot.voice_clients, guild=ctx.guild)

        # Перевірка, чи користувач в голосовому каналі
        if not ctx.author.voice:
            await ctx.send(f"{ctx.author.mention}, підключіться до голосового каналу спочатку!")
            return

        # Якщо бот не в каналі, підключаємо його
        if not voice_client or not voice_client.is_connected():
            logging.info(f"[{guild_id}] Bot not connected, invoking join command.") # Додано логування
            await ctx.invoke(self.join) # Викликаємо команду join
            voice_client = discord.utils.get(self.bot.voice_clients, guild=ctx.guild) # Оновлюємо voice_client
            if not voice_client: # Якщо підключення не вдалося
                logging.error(f"[{guild_id}] Failed to join voice channel after invoking join.") # Додано логування
                await ctx.send("Не вдалося підключитися до вашого голосового каналу.")
                return
            logging.info(f"[{guild_id}] Successfully joined channel: {voice_client.channel.name}") # Додано логування
        # Якщо бот в іншому каналі, переміщуємо
        elif voice_client.channel != ctx.author.voice.channel:
             try:
                 logging.info(f"[{guild_id}] Moving bot to channel: {ctx.author.voice.channel.name}") # Додано логування
                 await voice_client.move_to(ctx.author.voice.channel)
                 await ctx.send(f"Перемістився до каналу: **{ctx.author.voice.channel.name}**")
             except Exception as e:
                 logging.error(f"[{guild_id}] Error moving bot to channel {ctx.author.voice.channel.name}: {e}") # Додано логування
                 await ctx.send("Не вдалося переміститися до вашого каналу.")
                 return

        # Додаємо трек до черги
        if guild_id not in self.music_queues:
            self.music_queues[guild_id] = []

        # Поки що не отримуємо інформацію про трек, просто додаємо запит
        logging.info(f"[{guild_id}] Adding query to queue: {query}") # Додано логування
        self.music_queues[guild_id].append({'url': query, 'requester': ctx.author})
        await ctx.send(f"✅ Додано до черги: `{query}`")

        # Якщо нічого не грає, починаємо відтворення
        if not voice_client.is_playing() and not voice_client.is_paused():
            logging.info(f"[{guild_id}] Nothing playing, calling play_next_song.") # Додано логування
            await self.play_next_song(ctx)
        else:
            logging.info(f"[{guild_id}] Bot is already playing or paused. Query added to queue.") # Додано логування

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
            voice_client.stop() # Викличе after -> play_next_song
            await ctx.send(f"⏭️ Трек пропущено {ctx.author.mention}.")
        else:
            await ctx.send("Нічого пропускати.")

    @commands.command(name='stop', help='Зупинити відтворення та очистити чергу.')
    async def stop(self, ctx):
        """Зупиняє музику та очищає чергу."""
        guild_id = ctx.guild.id
        voice_client = discord.utils.get(self.bot.voice_clients, guild=ctx.guild)

        if voice_client and (voice_client.is_playing() or voice_client.is_paused()):
            self.music_queues[guild_id] = [] # Очищаємо чергу
            voice_client.stop() # Зупиняємо поточний трек
            if guild_id in self.current_song:
                del self.current_song[guild_id]
            # Видаляємо повідомлення з кнопками
            if guild_id in self.control_messages:
                try:
                    msg = await ctx.fetch_message(self.control_messages[guild_id])
                    await msg.delete()
                except (discord.NotFound, discord.Forbidden):
                    pass
                del self.control_messages[guild_id]
            await ctx.send("⏹️ Відтворення зупинено, чергу очищено.")
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

        # Поточний трек
        if guild_id in self.current_song:
            song_info = self.current_song[guild_id]
            duration_str = format_duration(song_info.get('duration'))
            embed.add_field(name="🎶 Зараз грає", value=f"[{song_info.get('title', 'Невідомий трек')}]({song_info.get('url', '#')}) | `{duration_str}` | Замовив(ла): {song_info['requester'].mention}", inline=False)

        # Наступні треки
        if queue:
            next_up = []
            for i, item in enumerate(queue[:10]): # Показуємо перші 10
                # Оскільки ми не завантажуємо інфо при додаванні, показуємо запит
                next_up.append(f"`{i+1}.` {item['url']} (Замовив(ла): {item['requester'].mention})")

            if next_up:
                 embed.add_field(name="⏭️ Далі в черзі", value="\n".join(next_up), inline=False)

            if len(queue) > 10:
                embed.set_footer(text=f"Ще {len(queue) - 10} треків у черзі...")
        elif guild_id in self.current_song: # Якщо грає трек, але черга порожня
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
        # Якщо бот залишився один у каналі
        if member.id == self.bot.user.id and after.channel is None: # Бот вийшов з каналу
             return # Вже оброблено командою leave/stop або play_next_song

        if before.channel and not after.channel and member.id != self.bot.user.id: # Користувач вийшов
            voice_client = discord.utils.get(self.bot.voice_clients, guild=member.guild)
            if voice_client and voice_client.channel == before.channel:
                # Перевіряємо, чи залишився хтось крім бота
                if len(voice_client.channel.members) == 1 and voice_client.channel.members[0].id == self.bot.user.id:
                    guild_id = member.guild.id
                    logging.info(f"Бот залишився один у каналі {before.channel.name}. Заплановано вихід.")
                    # Даємо трохи часу, можливо хтось повернеться
                    await asyncio.sleep(60)
                    # Перевіряємо ще раз
                    voice_client = discord.utils.get(self.bot.voice_clients, guild=member.guild) # Оновлюємо стан
                    if voice_client and voice_client.channel == before.channel and len(voice_client.channel.members) == 1:
                        logging.info(f"Виходжу з каналу {before.channel.name} через відсутність користувачів.")
                        # Потрібен контекст для leave_logic, це проблема
                        # Можна спробувати знайти текстовий канал для повідомлення
                        # Або просто викликати disconnect
                        if guild_id in self.music_queues:
                            self.music_queues[guild_id].clear()
                        if guild_id in self.current_song:
                            del self.current_song[guild_id]
                        if guild_id in self.control_messages:
                             # Потрібен доступ до каналу, де було повідомлення
                             # Це ускладнює видалення повідомлення тут
                             del self.control_messages[guild_id]
                        await voice_client.disconnect()
                        # Повідомлення про вихід (опціонально, знайти канал)
                        # general_channel = discord.utils.find(lambda c: c.name == 'general', member.guild.text_channels)
                        # if general_channel:
                        #    await general_channel.send("Вийшов з голосового каналу через відсутність користувачів.")


# Функція для додавання кога до бота (зазвичай викликається в main.py)
async def setup(bot):
    await bot.add_cog(MusicCog(bot))