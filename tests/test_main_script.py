import pytest
import sys
import os
import asyncio
from unittest.mock import Mock, AsyncMock, patch, MagicMock

# Patch load_dotenv before anything imports config
with patch('dotenv.load_dotenv'):
    with patch('os.path.exists', return_value=False), \
         patch('os.makedirs'), \
         patch('atexit.register'), \
         patch('builtins.open', MagicMock()), \
         patch('discord_music_bot.healthcheck.start_zombie_cleanup'):
        import main
        import discord
        from discord.ext import commands

@pytest.mark.asyncio
async def test_main_load_cogs():
    with patch('os.listdir', return_value=['music_cog.py', '_hidden.py', 'test.txt']):
        with patch.object(main.bot, 'load_extension', new_callable=AsyncMock) as mock_load:
            await main.load_cogs()
            mock_load.assert_called_once_with('discord_music_bot.cogs.music_cog')

@pytest.mark.asyncio
async def test_main_load_cogs_error():
    with patch('os.listdir', return_value=['fail_cog.py']):
        with patch.object(main.bot, 'load_extension', side_effect=Exception("Load Fail")):
            await main.load_cogs()

@pytest.mark.asyncio
async def test_on_ready_logic():
    main.bot.user = Mock(name="BotName", id=123)
    with patch('main.load_cogs', new_callable=AsyncMock), \
         patch.object(main.bot.tree, 'sync', new_callable=AsyncMock) as mock_sync, \
         patch.object(main.bot, 'change_presence', new_callable=AsyncMock):
        
        await main.on_ready()
        mock_sync.assert_called()
        
        mock_sync.side_effect = Exception("Sync Fail")
        await main.on_ready()

@pytest.mark.asyncio
async def test_on_command_error_cases():
    ctx = Mock()
    ctx.command.name = "test"
    ctx.send = AsyncMock()
    
    await main.on_command_error(ctx, commands.CommandNotFound())
    ctx.send.assert_called()
    
    await main.on_command_error(ctx, commands.MissingRequiredArgument(Mock()))
    await main.on_command_error(ctx, commands.CheckFailure())
    await main.on_command_error(ctx, commands.CommandInvokeError(Exception("Internal")))
    await main.on_command_error(ctx, Exception("Unknown"))

@pytest.mark.asyncio
async def test_main_entry_point():
    with patch('ssl.create_default_context'), \
         patch('certifi.where', return_value="path"), \
         patch('discord.opus.is_loaded', return_value=False), \
         patch('discord.opus.load_opus'), \
         patch.object(main.bot, 'start', new_callable=AsyncMock) as mock_start:
        
        await main.main()
        mock_start.assert_called()

def test_check_single_instance_exists():
    with patch('os.path.exists', return_value=True), \
         patch('builtins.open', MagicMock()), \
         patch('os.kill', side_effect=[None, OSError()]):
        
        with patch('sys.exit') as mock_exit:
            main.check_single_instance()
            mock_exit.assert_called_with(1)
        
        with patch('os.remove') as mock_remove:
            main.check_single_instance()
            mock_remove.assert_called()

def test_check_single_instance_invalid_file():
    with patch('os.path.exists', return_value=True), \
         patch('builtins.open', side_effect=ValueError()):
        with patch('os.remove') as mock_remove:
            main.check_single_instance()
            mock_remove.assert_called()
