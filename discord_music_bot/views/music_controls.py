import discord
import asyncio
import logging
from discord_music_bot import consts
from discord_music_bot.utils import format_duration
from discord_music_bot.views.history_view import HistoryView


class VolumeModal(discord.ui.Modal, title="Гучність"):
    """Модальне вікно для встановлення гучності."""
    volume_input = discord.ui.TextInput(
        label="Гучність (0-200%)",
        placeholder="Наприклад: 50",
        max_length=3,
        required=True
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
                # Зберігаємо гучність для наступних треків
                cog = interaction.client.get_cog('MusicCog')
                if cog:
                    cog._guild_volumes[interaction.guild.id] = clamped / 100.0
                emoji = "🔇" if clamped == 0 else "🔉" if clamped < 50 else "🔊"
                await interaction.response.send_message(f"{emoji} Гучність: **{clamped}%**", ephemeral=True)
            else:
                await interaction.response.send_message("Зараз нічого не грає.", ephemeral=True)
        except ValueError:
            await interaction.response.send_message("❌ Введіть число від 0 до 200.", ephemeral=True)


class MusicControls(discord.ui.View):
    """Панель керування плеєром (кнопки під embed-повідомленням)."""
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
            history = self.cog.history_service._history.get(guild_id, [])
            if not history:
                # Спробувати завантажити з БД
                db_tracks = await self.cog.repository.get_history(guild_id, limit=20)
                if db_tracks:
                    for t in reversed(db_tracks):
                        self.cog.history_service._history.setdefault(guild_id, []).append({
                            'title': t['title'],
                            'url': t.get('url', ''),
                            'webpage_url': t.get('url', ''),
                            'duration': t.get('duration'),
                            'thumbnail': t.get('thumbnail'),
                            'requester': None
                        })
                    history = self.cog.history_service._history.get(guild_id, [])
            
            if not history:
                await interaction.followup.send("Немає попередніх треків.", ephemeral=True)
                return
            
            # Беремо попередній трек з історії
            prev_track = self.cog.history_service.get_last_track(guild_id)
            
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
            await self.cog.on_skip_automix_feedback(interaction.guild.id)
            voice_client.stop()
            await interaction.response.send_message(f"⏭️ Трек пропущено {interaction.user.mention}.", ephemeral=False)
        else:
            await interaction.response.send_message("Нічого пропускати.", ephemeral=True)

    @discord.ui.button(label="Черга", style=discord.ButtonStyle.secondary, emoji=consts.EMOJI_QUEUE, custom_id="queue", row=0)
    async def queue_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        from discord_music_bot.views.queue_view import QueueView
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

    @discord.ui.button(label="Mix", style=discord.ButtonStyle.secondary, emoji="🎛️", custom_id="mix_settings", row=1)
    async def mix_settings_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Швидкі налаштування Automix + fade-out без slash-команд."""
        from discord_music_bot import consts as _consts

        class _MixSettingsView(discord.ui.View):
            def __init__(self, cog, guild_id: int):
                super().__init__(timeout=_consts.TIMEOUT_VIEW)
                self.cog = cog
                self.guild_id = guild_id
                self._sync_toggle_style()

            def _status_text(self) -> str:
                enabled = self.cog._automix_enabled.get(
                    self.guild_id, _consts.AUTOMIX_DEFAULT_ENABLED
                )
                mode = self.cog._automix_strategy_mode.get(
                    self.guild_id, _consts.AUTOMIX_STRATEGY_DEFAULT
                )
                fade = float(
                    self.cog._fade_seconds.get(
                        self.guild_id, _consts.DEFAULT_FADE_SECONDS
                    )
                )
                state = "ON" if enabled else "OFF"
                return (
                    "🎛️ **Mix settings**\n"
                    f"• Automix: **{state}**\n"
                    f"• Mode: **{mode}**\n"
                    f"• Fade-out: **{fade:.1f}s**"
                )

            def _sync_toggle_style(self):
                """Підсвічує кнопку ON/OFF: зелений=ON, червоний=OFF."""
                enabled = self.cog._automix_enabled.get(
                    self.guild_id,
                    _consts.AUTOMIX_DEFAULT_ENABLED,
                )
                for child in self.children:
                    if isinstance(child, discord.ui.Button) and child.custom_id == "mix_toggle_automix":
                        child.style = discord.ButtonStyle.success if enabled else discord.ButtonStyle.danger
                        child.label = "Automix ON" if enabled else "Automix OFF"
                        break

            async def _bump_player(self, interaction: discord.Interaction):
                try:
                    await self.cog.update_player(interaction.guild, interaction.channel)
                except Exception:
                    pass

            @discord.ui.button(
                label="Automix OFF",
                style=discord.ButtonStyle.danger,
                emoji="✅",
                custom_id="mix_toggle_automix",
                row=0,
            )
            async def toggle_automix(self, i: discord.Interaction, button: discord.ui.Button):
                guild_id = i.guild.id
                # Load persisted state if cache is empty
                if guild_id not in self.cog._automix_settings_cache:
                    await self.cog._ensure_automix_state_loaded(guild_id)

                current = self.cog._automix_enabled.get(guild_id, _consts.AUTOMIX_DEFAULT_ENABLED)
                new_value = not current
                self.cog._automix_enabled[guild_id] = new_value
                self.cog._automix_settings_cache.setdefault(
                    guild_id,
                    {
                        "enabled": new_value,
                        "strategy": self.cog._automix_strategy_mode.get(
                            guild_id, _consts.AUTOMIX_STRATEGY_DEFAULT
                        ),
                    },
                )
                self.cog._automix_settings_cache[guild_id]["enabled"] = new_value
                asyncio.ensure_future(self.cog.repository.set_automix_enabled(guild_id, new_value))

                button.style = discord.ButtonStyle.success if new_value else discord.ButtonStyle.danger
                button.label = "Automix ON" if new_value else "Automix OFF"
                await i.response.edit_message(content=self._status_text(), view=self)
                await self._bump_player(i)
                if new_value:
                    await i.followup.send("🎛️ Automix **увімкнено**.", ephemeral=True)
                else:
                    await i.followup.send("🎛️ Automix **вимкнено**.", ephemeral=True)

            @discord.ui.select(
                placeholder="Automix режим",
                min_values=1,
                max_values=1,
                options=[
                    discord.SelectOption(label="A/B (50% топ / 50% explore)", value="ab_split"),
                    discord.SelectOption(label="Лише top_weighted", value="top_weighted"),
                    discord.SelectOption(label="Лише history_explore", value="history_explore"),
                ],
                custom_id="mix_automix_mode_select",
            )
            async def automix_mode_select(self, i: discord.Interaction, select: discord.ui.Select):
                val = select.values[0]
                if val not in _consts.AUTOMIX_VALID_STRATEGIES:
                    await i.response.send_message("Невідомий режим.", ephemeral=True)
                    return
                guild_id = i.guild.id
                self.cog._automix_settings_cache.setdefault(
                    guild_id,
                    {
                        "enabled": self.cog._automix_enabled.get(guild_id, _consts.AUTOMIX_DEFAULT_ENABLED),
                        "strategy": val,
                    },
                )
                self.cog._automix_settings_cache[guild_id]["strategy"] = val
                self.cog._automix_strategy_mode[guild_id] = val
                asyncio.ensure_future(self.cog.repository.set_automix_strategy(guild_id, val))
                await i.response.edit_message(content=self._status_text(), view=self)
                await self._bump_player(i)
                await i.followup.send(f"🎛️ Automix режим: **{val}**", ephemeral=True)

            @discord.ui.select(
                placeholder="Fade-out (секунди)",
                min_values=1,
                max_values=1,
                options=[
                    discord.SelectOption(label="0 (вимкнено)", value="0"),
                    discord.SelectOption(label="3s", value="3"),
                    discord.SelectOption(label="6s", value="6"),
                    discord.SelectOption(label="8s", value="8"),
                    discord.SelectOption(label="10s", value="10"),
                    discord.SelectOption(label="15s", value="15"),
                ],
                custom_id="mix_fade_select",
            )
            async def fade_select(self, i: discord.Interaction, select: discord.ui.Select):
                try:
                    s = float(select.values[0])
                except Exception:
                    await i.response.send_message("Некоректне значення.", ephemeral=True)
                    return
                s = max(_consts.FADE_SECONDS_MIN, min(_consts.FADE_SECONDS_MAX, s))
                self.cog._fade_seconds[i.guild.id] = s
                await i.response.edit_message(content=self._status_text(), view=self)
                await self._bump_player(i)
                if s <= 0:
                    await i.followup.send("🔇 Fade-out вимкнено.", ephemeral=True)
                else:
                    await i.followup.send(f"🎚️ Fade-out: **{s:.1f}с**", ephemeral=True)

            @discord.ui.button(
                label="Закрити",
                style=discord.ButtonStyle.secondary,
                emoji="❌",
                custom_id="mix_close",
                row=2,
            )
            async def close_mix(self, i: discord.Interaction, button: discord.ui.Button):
                await i.response.edit_message(content="Налаштування Mix закрито.", view=None)
                await self._bump_player(i)

        mix_view = _MixSettingsView(self.cog, interaction.guild.id)
        await interaction.response.send_message(
            mix_view._status_text(),
            view=mix_view,
            ephemeral=True,
        )

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
            db_history = await self.cog.repository.get_history(guild_id, limit=1000)
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

            await interaction.followup.send(embed=embed, view=HistoryView(self.cog, guild_id), ephemeral=True)
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

            from discord_music_bot.views.dismiss_view import DismissView
            await interaction.response.send_message(embed=embed, view=DismissView(), ephemeral=True)
        except Exception as e:
            self.cog.logger.error(f"Stats button error: {e}", exc_info=True)
            await interaction.response.send_message("❌ Помилка отримання статистики.", ephemeral=True)
