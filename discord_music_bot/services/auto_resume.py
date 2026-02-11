"""
Auto-Resume сервіс — відновлює стан бота після рестарту.
Зчитує збережені guild states з БД та перепідключається до голосових каналів.
"""

import asyncio
import logging
from discord_music_bot.repository import MusicRepository

logger = logging.getLogger('MusicBot.AutoResume')


async def auto_resume(bot, cog) -> int:
    """
    Відновлює стан бота для всіх серверів де він був активний.
    
    Повертає кількість відновлених серверів.
    """
    repository: MusicRepository = cog.repository
    resumed_count = 0

    try:
        active_guilds = await repository.get_all_active_guilds()
        if not active_guilds:
            logger.info("Auto-Resume: немає активних серверів для відновлення.")
            return 0

        logger.info(f"Auto-Resume: знайдено {len(active_guilds)} сервер(ів) для відновлення.")

        for guild_state in active_guilds:
            guild_id = guild_state['guild_id']
            voice_channel_id = guild_state['voice_channel_id']
            text_channel_id = guild_state['text_channel_id']
            track_url = guild_state['current_track_url']
            track_title = guild_state.get('current_track_title', 'Unknown')

            try:
                guild = bot.get_guild(guild_id)
                if not guild:
                    logger.warning(f"Auto-Resume: Guild {guild_id} не знайдено (бот не на сервері?). Очищаємо стан.")
                    await repository.clear_guild_state(guild_id)
                    continue

                # Знайти голосовий канал
                voice_channel = guild.get_channel(voice_channel_id)
                if not voice_channel:
                    logger.warning(f"Auto-Resume: Voice channel {voice_channel_id} не знайдено у {guild.name}. Очищаємо стан.")
                    await repository.clear_guild_state(guild_id)
                    continue

                # Перевірити чи є люди в каналі (не підключатися до порожнього)
                human_members = [m for m in voice_channel.members if not m.bot]
                if not human_members:
                    logger.info(f"Auto-Resume: Канал {voice_channel.name} ({guild.name}) порожній, пропускаємо.")
                    await repository.clear_guild_state(guild_id)
                    continue

                # Підключитися до голосового каналу
                logger.info(f"Auto-Resume: Підключаємось до {voice_channel.name} ({guild.name})...")
                voice_client = await voice_channel.connect(timeout=30.0, reconnect=True)

                # Завантажити чергу з БД
                await cog.queue_service.load_from_db(guild_id)

                # Зберегти text channel для повідомлень
                if text_channel_id:
                    cog.player_channels[guild_id] = text_channel_id

                # Додати поточний трек на початок черги для відтворення
                cog.queue_service.push_front(guild_id, {
                    'url': track_url,
                    'webpage_url': track_url,
                    'title': track_title,
                    'duration': guild_state.get('current_track_duration'),
                    'thumbnail': guild_state.get('current_track_thumbnail'),
                    'requester': None,  # Requester невідомий після рестарту
                })

                # Почати відтворення
                await cog.play_next_song(guild, voice_client)

                # Повідомити в текстовий канал
                if text_channel_id:
                    text_channel = guild.get_channel(text_channel_id)
                    if text_channel:
                        queue = cog.queue_service.get_queue(guild_id)
                        queue_info = f" (ще {len(queue)} в черзі)" if queue else ""
                        await text_channel.send(
                            f"🔄 **Auto-Resume:** Бот повернувся після рестарту!\n"
                            f"▶️ Продовжую з: **{track_title}**{queue_info}"
                        )

                resumed_count += 1
                logger.info(f"Auto-Resume: Відновлено {guild.name} — {track_title}")

                # Маленька пауза між серверами щоб не перевантажити
                await asyncio.sleep(1)

            except Exception as e:
                logger.error(f"Auto-Resume: Помилка для guild {guild_id}: {e}", exc_info=True)
                # Очищаємо стан щоб не зациклюватись при наступному рестарті
                await repository.clear_guild_state(guild_id)
                continue

    except Exception as e:
        logger.error(f"Auto-Resume: Критична помилка: {e}", exc_info=True)

    logger.info(f"Auto-Resume: завершено, відновлено {resumed_count} сервер(ів).")
    return resumed_count
