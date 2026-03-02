import discord
from discord_music_bot import consts
from discord_music_bot.utils import format_duration


class SearchResultsView(discord.ui.View):
    """Вікно результатів пошуку з кнопками вибору треку."""
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
