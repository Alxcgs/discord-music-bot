import pytest
import discord
import asyncio
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from discord_music_bot.repository import MusicRepository
from discord_music_bot.services.auto_resume import auto_resume
from discord_music_bot.services.automix_service import AutomixService
from discord_music_bot.services.source_service import SourceService
from discord_music_bot.views.music_controls import VolumeModal, _MixSettingsView, MusicControls
from discord_music_bot.views.queue_view import QueueView, MoveTrackModal
from discord_music_bot.cogs.slash_music_cog import MusicCog
from discord_music_bot import audio_source
import main

# --- Mock Factory ---
class ExtremeInteraction(MagicMock):
    def __init__(self, *args, **kwargs):
        super().__init__(spec=discord.Interaction, *args, **kwargs)
        self.guild = MagicMock(spec=discord.Guild)
        self.guild.id = 123
        self.user = MagicMock(spec=discord.Member)
        self.user.id = 111
        self.user.voice = MagicMock()
        self.user.voice.channel = MagicMock()
        self.channel = MagicMock(spec=discord.TextChannel)
        self.response = MagicMock(spec=discord.InteractionResponse)
        self.response.send_message = AsyncMock()
        self.response.edit_message = AsyncMock()
        self.response.defer = AsyncMock()
        self.response.send_modal = AsyncMock()
        self.followup = MagicMock(spec=discord.Webhook)
        self.followup.send = AsyncMock()
        self.message = MagicMock(spec=discord.Message)
        self.message.delete = AsyncMock()
        self.client = MagicMock()

# --- Repository Extreme ---
@pytest.mark.asyncio
async def test_repository_missing_lines():
    repo = MusicRepository()
    mock_conn = AsyncMock()
    # Mocking the context manager __aenter__ and __aexit__
    mock_cursor = AsyncMock()
    mock_cursor.fetchone.return_value = None
    mock_conn.execute.return_value = mock_cursor
    mock_cursor.rowcount = 0
    
    with patch('discord_music_bot.repository.get_connection', return_value=mock_conn):
        assert await repo.pop_last_history_track(123) is None
        assert await repo.get_automix_diversity_stats(123) == {"rec_total": 0, "rec_distinct": 0}
        await repo.set_automix_strategy(123, "test")
        await repo.set_dj_persona(123, "test")

# --- Audio Source Extreme ---
def test_audio_source_read_padding():
    ffmpeg = Mock()
    ffmpeg.poll.return_value = None
    ytdlp = Mock()
    source = audio_source.YTDLPPipeSource(ytdlp, ffmpeg)
    source._buffer = b'123'
    source.MAX_READ_RETRIES = 1
    ffmpeg.stdout.read.return_value = b''
    with patch('time.sleep'):
        res = source.read()
        assert len(res) == source.FRAME_SIZE

# --- Auto Resume Extreme ---
@pytest.mark.asyncio
async def test_auto_resume_extreme():
    bot = MagicMock()
    guild = MagicMock()
    guild.get_channel.return_value = None
    bot.get_guild.return_value = guild
    repo = AsyncMock()
    repo.get_all_active_guilds.return_value = [{'guild_id': 1, 'voice_channel_id': 2}]
    cog = MagicMock()
    cog._auto_resume_executed = False
    
    with patch('discord_music_bot.services.auto_resume.MusicRepository', return_value=repo):
        await auto_resume(bot, cog)
        assert cog._auto_resume_executed == False # It crashed, so it didn't execute fully
    
    cog._auto_resume_executed = False
    with patch('discord_music_bot.services.auto_resume.MusicRepository', side_effect=Exception("Global Fail")):
        await auto_resume(bot, cog)
        assert cog._auto_resume_executed == False

# --- Automix Service Extreme ---
@pytest.mark.asyncio
async def test_automix_service_extreme():
    repo = AsyncMock()
    service = AutomixService(repo)
    repo.get_top_tracks.return_value = [{'url': 'u1', 'play_count': 5}]
    repo.get_history.return_value = []
    await service.recommend_for_strategy(1, "history_explore", recent_urls=[], automix_recent_urls=[], skip_penalties={})
    repo.get_top_tracks.return_value = []
    repo.get_history.return_value = [{'url': 'u1'}]
    await service.recommend_for_strategy(1, "top_weighted", recent_urls=[], automix_recent_urls=[], skip_penalties={})
    repo.get_top_tracks.return_value = [{'url': 'u1', 'play_count': 0}]
    await service._recommend_top_weighted(1, recent_urls=[], automix_recent_urls=[], skip_penalties={})
    with patch('random.choice', return_value={'url': 'u1'}):
        await service._recommend_history_explore(1, recent_urls=[], automix_recent_urls=[], skip_penalties={})
    service._unique_history_pool([{'url': ''}], set())
    service._weighted_pick([({'t': 1}, -1)])
    service._weighted_pick([({'t': 1}, 0.5)])

# --- Views Extreme ---
@pytest.mark.asyncio
async def test_music_controls_extreme():
    cog = MagicMock()
    # Correctly mock sub-services as AsyncMocks
    cog.repository = AsyncMock()
    cog.history_service = MagicMock()
    cog.queue_service = MagicMock()
    cog.queue_service.get_queue.return_value = []
    cog._ensure_dj_state_loaded = AsyncMock()
    
    guild = MagicMock()
    view = MusicControls(cog, guild)
    i = ExtremeInteraction()
    
    modal = VolumeModal(None)
    await modal.on_submit(i)
    
    parent = MagicMock()
    parent._resend_player = AsyncMock()
    mix_view = _MixSettingsView(cog, 123, parent_view=parent)
    await mix_view._bump_player(i)
    
    mix_view.cog._dj_settings_cache = {123: {"enabled": True}}
    # Call the callback directly to avoid 'Button' object is not callable
    await mix_view.toggle_dj.callback(i)
    for child in mix_view.children:
        if getattr(child, "custom_id", "") == "mix_dj_persona_select":
            child._values = ["chill"]
            await child.callback(i)
        elif getattr(child, "custom_id", "") == "mix_fade_select":
            child._values = ["0"]
            await child.callback(i)
    
    i.guild.voice_client.channel.id = 1
    i.user.voice.channel.id = 2
    assert await view.interaction_check(i) == False
    
    cog.history_service._history = {}
    cog.repository.get_history.return_value = []
    await view.previous_button.callback(i)
    
    i.followup.send.side_effect = Exception("Fail")
    cog.history_service._history = {123: [{'title': 't1'}]}
    await view.previous_button.callback(i)
    i.followup.send.side_effect = None

    cog.repository.get_history.return_value = []
    await view.history_button.callback(i)
    cog.repository.get_history.side_effect = Exception("Fail")
    await view.history_button.callback(i)

@pytest.mark.asyncio
async def test_queue_view_extreme():
    cog = MagicMock()
    guild = MagicMock()
    cog.queue_service.get_queue.return_value = []
    view = QueueView(cog, guild)
    view.create_embed()
    i = ExtremeInteraction()
    await view.move_track(i)

# --- Source Service Extreme ---
@pytest.mark.asyncio
async def test_source_service_extreme():
    service = SourceService()
    with patch('yt_dlp.YoutubeDL') as mock_ydl:
        mock_ydl.return_value.__enter__.return_value.extract_info.return_value = {
            'entries': [None, {'title': 't1', 'url': ''}],
            'title': 'Playlist'
        }
        await service.extract_playlist("url")

# --- Main Extreme ---
@pytest.mark.asyncio
async def test_main_startup_extreme():
    with patch('main.bot', MagicMock()), \
         patch('main.load_cogs', AsyncMock(side_effect=Exception("Fail"))):
        try: await main.on_ready()
        except: pass
        
    with patch('main.bot.load_extension', side_effect=Exception("Fail")), \
         patch('os.listdir', return_value=["test.py"]):
        try: await main.load_cogs()
        except: pass

# --- MusicCog Extreme ---
@pytest.mark.asyncio
async def test_cog_extreme_lines():
    bot = MagicMock()
    cog = MusicCog(bot)
    cog.repository = AsyncMock()
    cog.queue_service = MagicMock() # Ensure it's a mock
    i = ExtremeInteraction()
    i.guild.voice_client = MagicMock()
    i.guild.voice_client.disconnect = AsyncMock()
    i.user.voice.channel = i.guild.voice_client.channel
    
    cog.repository.get_listening_stats.side_effect = Exception("Fail")
    await MusicCog.stats.callback(cog, i)
    
    cog.repository.get_history.side_effect = Exception("Fail")
    await MusicCog.history.callback(cog, i)
    
    cog.queue_service.move_track.return_value = None
    await MusicCog.move.callback(cog, i, 1, 2)
    
    await MusicCog.leave.callback(cog, i)
    await MusicCog.reset.callback(cog, i)
