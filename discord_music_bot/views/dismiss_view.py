import discord


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
