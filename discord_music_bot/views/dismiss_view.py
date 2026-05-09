import discord


class DismissView(discord.ui.View):
    """Кнопка 'Закрити' для ephemeral повідомлень."""
    def __init__(self):
        super().__init__(timeout=300)
        item = getattr(self, "dismiss_button", None)
        if item is not None and hasattr(item, "callback"):
            item.callback = self._dismiss_button_impl
        self.dismiss_button = self._dismiss_button_impl

    @discord.ui.button(label="Закрити", style=discord.ButtonStyle.danger, emoji="❌")
    async def dismiss_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._dismiss_button_impl(interaction, button)

    async def _dismiss_button_impl(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            await interaction.response.edit_message(content="✅ Закрито", embed=None, view=None, delete_after=0)
        except Exception:
            try:
                await interaction.message.delete()
            except Exception:
                pass
