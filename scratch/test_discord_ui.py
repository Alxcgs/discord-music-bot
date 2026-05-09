import discord
from discord.ui import View, Button

class TestView(View):
    @discord.ui.button(label="Test")
    async def test_button(self, interaction, button):
        pass

view = TestView()
print(f"Type of view.test_button: {type(view.test_button)}")
print(f"Has callback: {hasattr(view.test_button, 'callback')}")
