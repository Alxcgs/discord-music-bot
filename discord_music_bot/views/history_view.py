import discord
import logging
from discord_music_bot import consts


class HistoryView(discord.ui.View):
    """Вікно історії з кнопками 'Очистити історію' та 'Закрити'."""
    def __init__(self, cog, guild_id):
        super().__init__(timeout=300)
        self.cog = cog
        self.guild_id = guild_id

    @discord.ui.button(label="Очистити історію", style=discord.ButtonStyle.danger, emoji=consts.EMOJI_CLEAR)
    async def clear_history_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            self.cog.history_service.clear_history(self.guild_id)
            embed = discord.Embed(title="📜 Історія прослуховувань", color=consts.COLOR_EMBED_NORMAL)
            embed.add_field(name="⏪ Раніше грало", value="Поки порожньо", inline=False)
            embed.set_author(name=f"{consts.EMOJI_CLEAR} Історію очищено!")
            # Вимикаємо кнопку очищення після натискання
            button.disabled = True
            await interaction.response.edit_message(embed=embed, view=self)
        except Exception as e:
            logging.getLogger('MusicBot').error(f"Clear history error: {e}", exc_info=True)
            await interaction.response.send_message("❌ Помилка очищення історії.", ephemeral=True)

    @discord.ui.button(label="Закрити", style=discord.ButtonStyle.secondary, emoji="❌")
    async def dismiss_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            await interaction.response.edit_message(content="✅ Закрито", embed=None, view=None, delete_after=0)
        except Exception:
            try:
                await interaction.message.delete()
            except Exception:
                pass
