import discord
from discord import app_commands
from discord.ext import commands
import asyncio
import logging
from discord_music_bot.services.queue_service import QueueService
from discord_music_bot.services.player_service import PlayerService
from discord_music_bot.audio_source import YTDLSource
from discord_music_bot.utils import format_duration
from discord_music_bot.database import init_db
from discord_music_bot.repository import MusicRepository
from discord_music_bot.services.auto_resume import auto_resume
import yt_dlp
from discord_music_bot import consts



class VolumeModal(discord.ui.Modal, title="🔊 Гучність"):
    """Модальне вікно для встановлення гучності."""
    volume_input = discord.ui.TextInput(
        label="Гучність (0-200%)",
        placeholder="Наприклад: 50",
        required=True,
        max_length=3,
        default="50",
    )

    def __init__(self, voice_client):
        super().__init__()
        self.voice_client = voice_client
        if voice_client and voice_client.source and hasattr(voice_client.source, 'volume'):
            self.volume_input.default = str(int(voice_client.source.volume * 100))

    async def on_submit(self, interaction: discord.Interaction):
        try:
            value = int(self.volume_input.value)
            clamped = max(0, min(200, value))
            if self.voice_client and self.voice_client.source and hasattr(self.voice_client.source, 'volume'):
                self.voice_client.source.volume = clamped / 100.0
                emoji = "🔇" if clamped == 0 else "🔉" if clamped < 50 else "🔊"
                await interaction.response.send_message(f"{emoji} Гучність: **{clamped}%**", ephemeral=True)
            else:
                await interaction.response.send_message("Зараз нічого не грає.", ephemeral=True)
        except ValueError:
            await interaction.response.send_message("❌ Введіть число від 0 до 200.", ephemeral=True)


class MoveTrackModal(discord.ui.Modal, title="↕️ Перемістити трек"):
    from_pos = discord.ui.TextInput(
        label="З позиції (№)",
        placeholder="Наприклад: 3",
        max_length=4,
        required=True
    )
    to_pos = discord.ui.TextInput(
        label="На позицію (№)",
        placeholder="Наприклад: 1",
        max_length=4,
        required=True
    )

    def __init__(self, queue_view):
        super().__init__()
        self.queue_view = queue_view

    async def on_submit(self, interaction: discord.Interaction):
        try:
            from_p = int(self.from_pos.value)
            to_p = int(self.to_pos.value)
        except ValueError:
            await interaction.response.send_message("❗ Введіть числа.", ephemeral=True)
            return

        guild_id = interaction.guild.id
        queue = self.queue_view.cog.queue_service.get_queue(guild_id)

        if from_p < 1 or from_p > len(queue) or to_p < 1 or to_p > len(queue):
            await interaction.response.send_message(
                f"❗ Некоректні позиції. Допустимий діапазон: **1–{len(queue)}**.", ephemeral=True
            )
            return

        if from_p == to_p:
            await interaction.response.send_message("Трек вже на цій позиції.", ephemeral=True)
            return

        track = self.queue_view.cog.queue_service.move_track(guild_id, from_p, to_p)
        if not track:
            await interaction.response.send_message("❗ Помилка переміщення.", ephemeral=True)
            return

        # Оновити відображення черги
        qv = self.queue_view
        qv.queue = qv.cog.queue_service.get_queue(guild_id)
        qv.total_pages = max((len(qv.queue) - 1) // qv.items_per_page + 1, 1)
        qv.current_page = min(qv.current_page, qv.total_pages - 1)
        qv.update_buttons()
        embed = qv.create_embed()
        direction = "⬆️" if to_p < from_p else "⬇️"
        embed.set_author(name=f"{direction} {track.get('title', '?')[:40]}: #{from_p} → #{to_p}")
        await interaction.response.edit_message(embed=embed, view=qv)


class DismissView(discord.ui.View):
    """Кнопка 'Закрити' для ephemeral повідомлень."""
    def __init__(self):
        super().__init__(timeout=300)

    @discord.ui.button(label="Закрити", style=discord.ButtonStyle.danger, emoji="❌")
    async def dismiss_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            await interaction.response.edit_message(content="✅ Закрито", embed=None, view=None, delete_after=0)
        except Exception:
            try:
                await interaction.message.delete()
            except Exception:
                pass


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

    async def _resend_player(self, interaction: discord.Interaction):
        """Пересилає панель керування внизу чату."""
        await self.cog.update_player(interaction.guild, interaction.channel)

    @discord.ui.button(label="Попередній", style=discord.ButtonStyle.secondary, emoji=consts.EMOJI_PREVIOUS, custom_id="previous", row=0)
    async def previous_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild_id = interaction.guild.id
        
        if guild_id in self.cog.processing_buttons:
            await interaction.response.send_message("Зачекайте, обробляється попередня дія.", ephemeral=True)
            return
        
        self.cog.processing_buttons.add(guild_id)
        
        # Defer одразу — операція займає 4-5с (sleep + yt-dlp extraction)
        await interaction.response.defer()
        
        try:
            history = self.cog.queue_service._history.get(guild_id, [])
            if not history:
                # Спробувати завантажити з БД
                db_tracks = await self.cog.repository.get_history(guild_id, limit=20)
                if db_tracks:
                    for t in reversed(db_tracks):
                        self.cog.queue_service._history.setdefault(guild_id, []).append({
                            'title': t['title'],
                            'url': t.get('url', ''),
                            'webpage_url': t.get('url', ''),
                            'duration': t.get('duration'),
                            'thumbnail': t.get('thumbnail'),
                            'requester': None
                        })
                    history = self.cog.queue_service._history.get(guild_id, [])
            
            if not history:
                await interaction.followup.send("Немає попередніх треків.", ephemeral=True)
                return
            
            # Беремо попередній трек з історії
            prev_track = self.cog.queue_service.get_last_track(guild_id)
            
            # Зберігаємо поточний трек у чергу (щоб він грав далі після prev)
            if guild_id in self.cog.current_song:
                current = self.cog.current_song[guild_id].copy()
                current.pop('player', None)
                self.cog.queue_service.push_front(guild_id, current)
            
            # Додаємо prev на початок черги
            self.cog.queue_service.push_front(guild_id, prev_track)
            
            # Очищаємо current_song
            self.cog.current_song.pop(guild_id, None)
            
            voice_client = interaction.guild.voice_client
            
            # Блокуємо after-callback щоб він НЕ викликав play_next_song
            self.cog._skip_after_play.add(guild_id)
            
            if voice_client and (voice_client.is_playing() or voice_client.is_paused()):
                voice_client.stop()
            
            # Чекаємо поки after-callback відпрацює (і пропустить play_next_song)
            await asyncio.sleep(0.5)
            
            
            # Руками запускаємо наступний трек (без додавання в історію — current_song пустий)
            if voice_client and voice_client.is_connected():
                await self.cog.play_next_song(interaction.guild, voice_client)
            
            await interaction.followup.send(
                f"⏮️ Повертаємось до треку: {prev_track.get('title', 'Невідомий трек')}", 
                ephemeral=False
            )
            
        except Exception as e:
            self.cog.logger.error(f"Error in previous_button: {e}", exc_info=True)
            try:
                await interaction.followup.send("❌ Помилка при поверненні до попереднього треку.", ephemeral=True)
            except Exception:
                pass
        
        finally:
            self.cog._skip_after_play.discard(guild_id)
            self.cog.processing_buttons.discard(guild_id)

    @discord.ui.button(label="Пауза", style=discord.ButtonStyle.secondary, emoji=consts.EMOJI_PAUSE, custom_id="pause_resume", row=0)
    async def pause_resume_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        voice_client = interaction.guild.voice_client
        if voice_client and voice_client.is_playing():
            voice_client.pause()
            await interaction.response.defer()
            await self._resend_player(interaction)
        elif self.cog.player_service.is_paused(voice_client):
            self.cog.player_service.resume(voice_client)
            await interaction.response.defer()
            await self._resend_player(interaction)
        else:
            await interaction.response.send_message("Зараз нічого не грає.", ephemeral=True)

    @discord.ui.button(label="Пропустити", style=discord.ButtonStyle.secondary, emoji=consts.EMOJI_SKIP, custom_id="skip", row=0)
    async def skip_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        voice_client = interaction.guild.voice_client
        if voice_client and (voice_client.is_playing() or voice_client.is_paused()):
            voice_client.stop()
            await interaction.response.send_message(f"⏭️ Трек пропущено {interaction.user.mention}.", ephemeral=False)
        else:
            await interaction.response.send_message("Нічого пропускати.", ephemeral=True)

    @discord.ui.button(label="Черга", style=discord.ButtonStyle.secondary, emoji=consts.EMOJI_QUEUE, custom_id="queue", row=0)
    async def queue_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = QueueView(self.cog, interaction.guild)
        await interaction.response.send_message(embed=view.create_embed(), view=view, ephemeral=True)

    @discord.ui.button(label="Вийти", style=discord.ButtonStyle.secondary, emoji=consts.EMOJI_LEAVE, custom_id="leave", row=0)
    async def leave_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        voice_client = interaction.guild.voice_client
        if voice_client and voice_client.is_connected():
            await self.cog.leave_logic(interaction.guild)
            await interaction.response.send_message(f"👋 Бот вийшов з каналу за командою {interaction.user.mention}.", ephemeral=False)
            self.stop()
        else:
            await interaction.response.send_message("Бот не підключений до голосового каналу.", ephemeral=True)

    # --- Другий рядок кнопок ---

    @discord.ui.button(label="Гучність", style=discord.ButtonStyle.secondary, emoji="🔊", custom_id="volume_modal", row=1)
    async def volume_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        voice_client = interaction.guild.voice_client
        if voice_client and voice_client.source and hasattr(voice_client.source, 'volume'):
            modal = VolumeModal(voice_client)
            await interaction.response.send_modal(modal)
        else:
            await interaction.response.send_message("Зараз нічого не грає.", ephemeral=True)

    @discord.ui.button(label="Історія", style=discord.ButtonStyle.secondary, emoji=consts.EMOJI_HISTORY, custom_id="history", row=1)
    async def history_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild_id = interaction.guild.id
        try:
            await interaction.response.defer(ephemeral=True)
            # Завантажуємо всю історію з БД (всі сесії)
            db_history = await self.cog.repository.get_history(guild_id, limit=20)
            embed = discord.Embed(title="📜 Історія прослуховувань", color=consts.COLOR_EMBED_NORMAL)

            # Поточний трек
            if guild_id in self.cog.current_song:
                song = self.cog.current_song[guild_id]
                duration = format_duration(song.get('duration'))
                embed.add_field(name="🎶 Зараз грає", value=f"**{song['title'][:45]}** | `{duration}`", inline=False)

            if db_history:
                lines = []
                for i, t in enumerate(db_history, 1):
                    duration = format_duration(t.get('duration'))
                    played_at = t.get('played_at', '')[:16] if t.get('played_at') else ''
                    time_str = f" • {played_at}" if played_at else ''
                    lines.append(f"`{i}.` **{t.get('title', '?')[:30]}** | `{duration}`{time_str}")
                # Розбиваємо на чанки по 1024 символи (ліміт Discord)
                chunks = []
                current_chunk = []
                current_length = 0
                for line in lines:
                    if current_length + len(line) + 1 > 1000:
                        if current_chunk:
                            chunks.append("\n".join(current_chunk))
                        current_chunk = [line]
                        current_length = len(line)
                    else:
                        current_chunk.append(line)
                        current_length += len(line) + 1
                if current_chunk:
                    chunks.append("\n".join(current_chunk))
                for idx, chunk in enumerate(chunks):
                    name = "⏪ Раніше грало" if idx == 0 else "\u200b"
                    embed.add_field(name=name, value=chunk, inline=False)
                embed.set_footer(text=f"Показано останні {len(db_history)} трек(ів)")
            else:
                embed.add_field(name="⏪ Раніше грало", value="Поки порожньо", inline=False)

            await interaction.followup.send(embed=embed, view=DismissView(), ephemeral=True)
        except Exception as e:
            self.cog.logger.error(f"History button error: {e}", exc_info=True)
            await interaction.followup.send("❌ Помилка отримання історії.", ephemeral=True)

    @discord.ui.button(label="Статистика", style=discord.ButtonStyle.secondary, emoji=consts.EMOJI_STATS, custom_id="stats_btn", row=1)
    async def stats_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild_id = interaction.guild.id
        try:
            # Статистика за поточну сесію (з моменту запуску бота)
            session_tracks = self.cog._session_tracks.get(guild_id, [])
            embed = discord.Embed(title="📊 Статистика сесії", color=consts.COLOR_EMBED_NORMAL)

            total_seconds = sum(t.get('duration') or 0 for t in session_tracks)
            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60
            time_str = f"{hours}г {minutes}хв" if hours > 0 else f"{minutes}хв"

            embed.add_field(
                name="📈 За цю сесію",
                value=f"🎵 Треків програно: **{len(session_tracks)}**\n⏱️ Час: **{time_str}**",
                inline=False
            )

            if session_tracks:
                # Топ треки за сесію (по кількості відтворень)
                from collections import Counter
                title_counts = Counter(t.get('title', '?') for t in session_tracks)
                top = title_counts.most_common(5)
                top_text = "\n".join([
                    f"`{i+1}.` **{title[:35]}** — {count}x"
                    for i, (title, count) in enumerate(top)
                ])
                embed.add_field(name="🏆 Топ-5 за сесію", value=top_text, inline=False)

            await interaction.response.send_message(embed=embed, view=DismissView(), ephemeral=True)
        except Exception as e:
            self.cog.logger.error(f"Stats button error: {e}", exc_info=True)
            await interaction.response.send_message("❌ Помилка отримання статистики.", ephemeral=True)

class QueueView(discord.ui.View):
    def __init__(self, cog, guild, timeout=consts.TIMEOUT_VIEW):
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
            requester_line = f"\nЗамовив користувач: {song_info['requester'].mention}" if song_info.get('requester') else ""
            embed.add_field(
                name="🎶 Зараз грає",
                value=f"{current_track}{requester_line}",
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
                    if current_length + len(track) > consts.MAX_QUEUE_FIELD_LENGTH:
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

            total_duration = sum(item.get('duration') or 0 for item in self.queue)
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

        # Row 2: Shuffle + Move + Close
        shuffle_button = discord.ui.Button(style=discord.ButtonStyle.success, emoji=consts.EMOJI_SHUFFLE, label="Перемішати", custom_id="shuffle_queue", row=1, disabled=len(self.queue) < 2)
        shuffle_button.callback = self.shuffle_queue
        self.add_item(shuffle_button)

        move_button = discord.ui.Button(style=discord.ButtonStyle.primary, emoji=consts.EMOJI_MOVE, label="Перемістити", custom_id="move_track", row=1, disabled=len(self.queue) < 2)
        move_button.callback = self.move_track
        self.add_item(move_button)

        close_button = discord.ui.Button(style=discord.ButtonStyle.danger, emoji="❌", label="Закрити", custom_id="close_queue", row=1)
        close_button.callback = self.close_view
        self.add_item(close_button)

    async def _handle_page_change(self, interaction: discord.Interaction, new_page):
        self.queue = self.cog.queue_service.get_queue(self.guild.id)  # Update local queue ref
        self.total_pages = max((len(self.queue) - 1) // self.items_per_page + 1, 1)
        self.current_page = min(new_page, self.total_pages - 1)
        self.update_buttons()
        await interaction.response.edit_message(embed=self.create_embed(), view=self)

    async def first_page(self, interaction): await self._handle_page_change(interaction, 0)
    async def prev_page(self, interaction): await self._handle_page_change(interaction, max(0, self.current_page - 1))
    async def next_page(self, interaction): await self._handle_page_change(interaction, min(self.total_pages - 1, self.current_page + 1))
    async def last_page(self, interaction): await self._handle_page_change(interaction, self.total_pages - 1)
    async def refresh_page(self, interaction): await self._handle_page_change(interaction, self.current_page)
    async def shuffle_queue(self, interaction):
        guild_id = self.guild.id
        queue = self.cog.queue_service.get_queue(guild_id)
        if len(queue) < 2:
            await interaction.response.send_message("Недостатньо треків для перемішування.", ephemeral=True)
            return
        self.cog.queue_service.shuffle(guild_id)
        self.queue = self.cog.queue_service.get_queue(guild_id)
        self.current_page = 0
        self.total_pages = max((len(self.queue) - 1) // self.items_per_page + 1, 1)
        self.update_buttons()
        embed = self.create_embed()
        embed.set_author(name=f"{consts.EMOJI_SHUFFLE} Чергу перемішано! ({len(self.queue)} треків)")
        await interaction.response.edit_message(embed=embed, view=self)

    async def move_track(self, interaction):
        modal = MoveTrackModal(self)
        await interaction.response.send_modal(modal)

    async def close_view(self, interaction):
        try:
            await interaction.response.edit_message(content="✅ Закрито", embed=None, view=None, delete_after=0)
        except Exception:
            try:
                await interaction.message.delete()
            except Exception:
                pass


class SearchResultsView(discord.ui.View):
    def __init__(self, cog, user, results, timeout=consts.TIMEOUT_SEARCH_MENU):
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
        self.repository = MusicRepository()
        self.queue_service = QueueService(self.repository)
        self.player_service = PlayerService()
        self.current_song = {}
        self.control_messages = {}
        self.player_channels = {}
        self.processing_buttons = set()
        self._skip_after_play = set()  # guild_ids де after-callback має бути пропущений
        self._session_tracks = {}  # {guild_id: [track_dicts]} — треки за поточну сесію
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

    async def play_next_song(self, guild, voice_client):
        try:
            guild_id = guild.id
            if guild_id in self.current_song:
                # Додаємо в історію через QueueService (зберігає і в пам'ять, і в БД)
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
                self.queue_service.add_to_history(guild_id, history_track)
            
            queue = self.queue_service.get_queue(guild_id)
            if queue:
                item = self.queue_service.get_next_track(guild_id)
                try:
                    player = await self.player_service.play_stream(
                        voice_client, 
                        item['url'], 
                        self.bot.loop, 
                        lambda e: self.bot.loop.create_task(self.check_after_play(guild, voice_client, e))
                    )
                    
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
            voice_client = await interaction.user.voice.channel.connect(timeout=consts.TIMEOUT_VOICE_CONNECT, reconnect=True)
        
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

    @app_commands.command(name="reset", description="Скинути стан бота (якщо завис або не грає)")
    async def reset(self, interaction: discord.Interaction):
        await interaction.response.defer()
        
        guild_id = interaction.guild_id
        
        # 1. Очистка черги і стану
        self.queue_service.clear(guild_id)
        if guild_id in self.current_song: del self.current_song[guild_id]

        
        # 2. Примусовий дисконект
        voice_client = interaction.guild.voice_client
        if voice_client:
            await voice_client.disconnect(force=True)
            await interaction.followup.send("♻️ Бот перезавантажив з'єднання! Спробуйте `/join` або `/play` знову.")
        else:
            await interaction.followup.send("♻️ Чергу очищено (бот не був у голосовому каналі).")

    @app_commands.command(name="stop", description="Зупинити та очистити")
    async def stop(self, interaction: discord.Interaction):
        voice_client = interaction.guild.voice_client
        if voice_client:
            self.queue_service.clear(interaction.guild_id)

            self.player_service.stop(voice_client)
            await self.update_player(interaction.guild, interaction.channel)
            await voice_client.disconnect() # Force disconnect on stop to be sure
            await interaction.response.send_message("⏹️ Зупинено та відключено.")
        else:
            await interaction.response.send_message("Я не граю.", ephemeral=True)

    @app_commands.command(name="queue", description="Показати чергу")
    async def queue(self, interaction: discord.Interaction):
        view = QueueView(self, interaction.guild)
        await interaction.response.send_message(embed=view.create_embed(), view=view)

    @app_commands.command(name="shuffle", description="Перемішати чергу рандомно")
    async def shuffle(self, interaction: discord.Interaction):
        guild_id = interaction.guild_id
        queue = self.queue_service.get_queue(guild_id)
        if len(queue) < 2:
            await interaction.response.send_message("Недостатньо треків для перемішування.", ephemeral=True)
            return
        self.queue_service.shuffle(guild_id)
        queue = self.queue_service.get_queue(guild_id)

        embed = discord.Embed(
            title=f"{consts.EMOJI_SHUFFLE} Чергу перемішано!",
            color=consts.COLOR_EMBED_NORMAL
        )
        # Показуємо перші 5 треків нового порядку
        preview = "\n".join([
            f"`{i+1}.` **{t.get('title', '?')[:45]}**"
            for i, t in enumerate(queue[:5])
        ])
        if len(queue) > 5:
            preview += f"\n... та ще {len(queue) - 5} треків"
        embed.add_field(name="📑 Нова черга", value=preview, inline=False)
        embed.set_footer(text=f"Всього: {len(queue)} треків")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="move", description="Перемістити трек на іншу позицію")
    @app_commands.describe(from_pos="Поточна позиція треку", to_pos="Нова позиція треку")
    async def move(self, interaction: discord.Interaction, from_pos: int, to_pos: int):
        guild_id = interaction.guild_id
        queue = self.queue_service.get_queue(guild_id)

        if not queue:
            await interaction.response.send_message("Черга порожня.", ephemeral=True)
            return

        if from_pos < 1 or from_pos > len(queue) or to_pos < 1 or to_pos > len(queue):
            await interaction.response.send_message(
                f"Некоректні позиції. Допустимий діапазон: **1–{len(queue)}**.", ephemeral=True
            )
            return

        if from_pos == to_pos:
            await interaction.response.send_message("Трек вже на цій позиції.", ephemeral=True)
            return

        track = self.queue_service.move_track(guild_id, from_pos, to_pos)
        if not track:
            await interaction.response.send_message("Помилка переміщення.", ephemeral=True)
            return

        direction = "⬆️" if to_pos < from_pos else "⬇️"
        embed = discord.Embed(
            title=f"{consts.EMOJI_MOVE} Трек переміщено",
            color=consts.COLOR_EMBED_NORMAL
        )
        embed.add_field(
            name=track.get('title', 'Unknown')[:50],
            value=f"{direction} `#{from_pos}` → `#{to_pos}`",
            inline=False
        )
        # Показуємо оновлені сусідні позиції
        queue = self.queue_service.get_queue(guild_id)
        start = max(0, to_pos - 3)
        end = min(len(queue), to_pos + 2)
        context_lines = []
        for i in range(start, end):
            prefix = "▸ " if i == to_pos - 1 else "  "
            context_lines.append(f"{prefix}`{i+1}.` {queue[i].get('title', '?')[:40]}")
        embed.add_field(name="📑 Контекст", value="\n".join(context_lines), inline=False)
        await interaction.response.send_message(embed=embed)

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
