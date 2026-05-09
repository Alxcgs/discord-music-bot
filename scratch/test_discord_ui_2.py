import discord
from discord.ui import View, Button

class TestView(View):
    @discord.ui.button(label="Test")
    async def test_button(self, interaction, button):
        pass

print(f"Type of TestView.test_button: {type(TestView.test_button)}")
print(f"Attributes of TestView.test_button: {dir(TestView.test_button)}")
