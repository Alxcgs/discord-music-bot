import discord
from discord_music_bot import consts
from discord_music_bot.utils import format_duration


class MoveTrackModal(discord.ui.Modal, title="Перемістити трек"):
    """Модальне вікно для переміщення треку в черзі."""
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


class QueueView(discord.ui.View):
    """Вікно відображення черги з навігацією та управлінням."""
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

        # Row 2: Shuffle + Move + Clear + Close
        shuffle_button = discord.ui.Button(style=discord.ButtonStyle.success, emoji=consts.EMOJI_SHUFFLE, label="Перемішати", custom_id="shuffle_queue", row=1, disabled=len(self.queue) < 2)
        shuffle_button.callback = self.shuffle_queue
        self.add_item(shuffle_button)

        move_button = discord.ui.Button(style=discord.ButtonStyle.primary, emoji=consts.EMOJI_MOVE, label="Перемістити", custom_id="move_track", row=1, disabled=len(self.queue) < 2)
        move_button.callback = self.move_track
        self.add_item(move_button)

        clear_button = discord.ui.Button(style=discord.ButtonStyle.danger, emoji=consts.EMOJI_CLEAR, label="Очистити", custom_id="clear_queue", row=1, disabled=len(self.queue) == 0)
        clear_button.callback = self.clear_queue
        self.add_item(clear_button)

        close_button = discord.ui.Button(style=discord.ButtonStyle.danger, emoji="❌", label="Закрити", custom_id="close_queue", row=1)
        close_button.callback = self.close_view
        self.add_item(close_button)

    async def _bump_player(self, interaction: discord.Interaction):
        """Опускає головну панель керування в низ чату."""
        try:
            await self.cog.update_player(interaction.guild, interaction.channel)
        except Exception:
            pass

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
        await self._bump_player(interaction)

    async def move_track(self, interaction):
        modal = MoveTrackModal(self)
        await interaction.response.send_modal(modal)

    async def clear_queue(self, interaction):
        guild_id = self.guild.id
        self.cog.queue_service.clear(guild_id)
        self.queue = self.cog.queue_service.get_queue(guild_id)
        self.current_page = 0
        self.total_pages = 1
        self.update_buttons()
        embed = self.create_embed()
        embed.set_author(name=f"{consts.EMOJI_CLEAR} Чергу очищено!")
        await interaction.response.edit_message(embed=embed, view=self)
        await self._bump_player(interaction)

    async def close_view(self, interaction):
        try:
            await interaction.response.edit_message(content="✅ Закрито", embed=None, view=None, delete_after=0)
            await self._bump_player(interaction)
        except Exception:
            try:
                await interaction.message.delete()
            except Exception:
                pass
