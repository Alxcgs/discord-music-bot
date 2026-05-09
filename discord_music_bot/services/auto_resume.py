import asyncio
import logging
from datetime import datetime, timezone
from discord_music_bot.repository import MusicRepository
from discord_music_bot import consts

logger = logging.getLogger('MusicBot.AutoResume')


async def auto_resume(bot, cog) -> int:
    """
    Відновлює стан бота для всіх серверів де він був активний.
    
    Перевіряє:
    1. Наявність активних сесій у БД.
    2. Політику застарілості (staleness policy).
    3. Присутність людей у голосовому каналі.
    
    Повертає кількість відновлених серверів.
    """
    repository: MusicRepository = cog.repository
    resumed_count = 0

    try:
        active_guilds = await repository.get_all_active_guilds()
        if not active_guilds:
            logger.info("Auto-Resume: немає активних серверів для відновлення.")
            return 0

        logger.info(f"Auto-Resume: знайдено {len(active_guilds)} сесій у БД.")

        now = datetime.now(timezone.utc)

        for guild_state in active_guilds:
            guild_id = guild_state['guild_id']
            updated_at_str = guild_state.get('updated_at')
            
            # 1. Staleness Policy
            if updated_at_str:
                try:
                    # SQLite CURRENT_TIMESTAMP returns UTC time in format 'YYYY-MM-DD HH:MM:SS'
                    # We append ' +0000' to make it offset-aware for comparison
                    updated_at = datetime.strptime(updated_at_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                    diff = (now - updated_at).total_seconds()
                    
                    if diff > consts.AUTO_RESUME_STALENESS_THRESHOLD:
                        logger.info(f"Auto-Resume: сесія {guild_id} застаріла ({int(diff/3600)}г тому). Очищаємо.")
                        await repository.clear_guild_state(guild_id)
                        continue
                except Exception as e:
                    logger.warning(f"Auto-Resume: не вдалося розпарсити дату {updated_at_str}: {e}")

            voice_channel_id = guild_state['voice_channel_id']
            text_channel_id = guild_state['text_channel_id']
            track_url = guild_state['current_track_url']
            track_title = guild_state.get('current_track_title', 'Unknown')

            try:
                guild = bot.get_guild(guild_id)
                if not guild:
                    logger.warning(f"Auto-Resume: Guild {guild_id} не знайдено. Очищаємо стан.")
                    await repository.clear_guild_state(guild_id)
                    continue

                voice_channel = guild.get_channel(voice_channel_id)
                if not voice_channel:
                    logger.warning(f"Auto-Resume: Voice channel {voice_channel_id} не знайдено у {guild.name}. Очищаємо стан.")
                    await repository.clear_guild_state(guild_id)
                    continue

                # 2. Human presence check
                human_members = [m for m in voice_channel.members if not m.bot]
                if not human_members:
                    logger.info(f"Auto-Resume: Канал {voice_channel.name} ({guild.name}) порожній. Очищаємо стан.")
                    await repository.clear_guild_state(guild_id)
                    continue

                # 3. Reconnect
                logger.info(f"Auto-Resume: Відновлення {voice_channel.name} ({guild.name})...")
                voice_client = await voice_channel.connect(timeout=consts.TIMEOUT_VOICE_CONNECT, reconnect=True)

                await cog.queue_service.load_from_db(guild_id)

                if text_channel_id:
                    cog.player_channels[guild_id] = text_channel_id

                cog.queue_service.push_front(guild_id, {
                    'url': track_url,
                    'webpage_url': track_url,
                    'title': track_title,
                    'duration': guild_state.get('current_track_duration'),
                    'thumbnail': guild_state.get('current_track_thumbnail'),
                    'requester': None,
                })

                await cog.play_next_song(guild, voice_client)

                if text_channel_id:
                    text_channel = guild.get_channel(text_channel_id)
                    if text_channel:
                        queue = cog.queue_service.get_queue(guild_id)
                        queue_info = f" (ще {len(queue)} в черзі)" if queue else ""
                        await text_channel.send(
                            f"🔄 **Auto-Resume:** Бот повернувся!\n"
                            f"▶️ Продовжую з: **{track_title}**{queue_info}"
                        )
                        await asyncio.sleep(1)
                        await cog.update_player(guild, text_channel)

                resumed_count += 1
                await asyncio.sleep(1)

            except Exception as e:
                logger.error(f"Auto-Resume failure for {guild_id}: {e}")
                await repository.clear_guild_state(guild_id)
                continue

    except Exception as e:
        logger.error(f"Auto-Resume critical error: {e}")

    return resumed_count
