"""
SearchSourceService — сервіс пошуку та витягування інформації про треки.
Інкапсулює роботу з yt-dlp для пошуку, отримання метаданих та обробки плейлистів.
"""

import asyncio
import logging
from typing import Optional, Dict, List, Tuple, Any

import yt_dlp

from discord_music_bot import consts


logger = logging.getLogger('MusicBot.SearchService')


class SearchSourceService:
    """Сервіс для пошуку треків та обробки плейлистів (yt-dlp)."""

    def __init__(self, loop: asyncio.AbstractEventLoop):
        self._loop = loop
        self._light_opts = consts.YTDL_OPTIONS_LIGHT

    # ── Single Track ──────────────────────────────────────────────

    async def get_video_info(self, url: str) -> Optional[Dict[str, Any]]:
        """Отримує метадані одного треку за URL або пошуковим запитом."""
        search_url = (
            url
            if any(x in url.lower() for x in ['youtube.com', 'youtu.be', 'soundcloud.com'])
            else f"ytsearch:{url}"
        )
        is_soundcloud = 'soundcloud.com' in url.lower()
        ydl_opts = self._light_opts.copy()
        if is_soundcloud:
            ydl_opts['extract_flat'] = False

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            try:
                info = await self._loop.run_in_executor(
                    None, lambda: ydl.extract_info(search_url, download=False)
                )
                if not info:
                    return None
                if 'entries' in info:
                    info = info['entries'][0]
                return {
                    'title': info.get('title') or info.get('fulltitle') or 'Unknown',
                    'url': info.get('webpage_url', url) or info.get('url', url),
                    'duration': info.get('duration'),
                    'thumbnail': info.get('thumbnail'),
                }
            except Exception as e:
                logger.error(f"Error extracting info: {e}")
                return None

    # ── Multi-Search ──────────────────────────────────────────────

    async def search_videos(
        self, query: str, max_results: int = 10
    ) -> List[Dict[str, Any]]:
        """Шукає кілька відео за текстовим запитом для меню вибору."""
        search_url = f"ytsearch{max_results}:{query}"
        with yt_dlp.YoutubeDL(self._light_opts) as ydl:
            try:
                info = await self._loop.run_in_executor(
                    None, lambda: ydl.extract_info(search_url, download=False)
                )
                if not info or 'entries' not in info:
                    return []
                results = []
                for entry in info['entries']:
                    if entry:
                        results.append({
                            'title': entry.get('title', 'Unknown'),
                            'url': entry.get('webpage_url', entry.get('url', '')),
                            'webpage_url': entry.get('webpage_url', entry.get('url', '')),
                            'duration': entry.get('duration'),
                            'thumbnail': entry.get('thumbnail'),
                        })
                return results
            except Exception as e:
                logger.error(f"Error searching videos: {e}")
                return []

    # ── Playlist ──────────────────────────────────────────────────

    async def extract_playlist(
        self, url: str
    ) -> Tuple[Optional[str], List[Dict[str, Any]]]:
        """Витягує список треків з плейлиста (тільки метадані, швидко)."""
        is_soundcloud = 'soundcloud.com' in url.lower()
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False if is_soundcloud else 'in_playlist',
            'skip_download': True,
            'ignoreerrors': True,
        }
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = await self._loop.run_in_executor(
                    None, lambda: ydl.extract_info(url, download=False)
                )
                if not info or 'entries' not in info:
                    return None, []

                playlist_title = info.get('title', 'Плейлист')
                tracks: List[Dict[str, Any]] = []
                for entry in info['entries']:
                    if not entry:
                        continue
                    track_url = entry.get('url') or entry.get('webpage_url', '')
                    if not track_url:
                        continue
                    if not track_url.startswith('http'):
                        track_url = f"https://www.youtube.com/watch?v={track_url}"
                    tracks.append({
                        'title': entry.get('title', 'Unknown'),
                        'url': track_url,
                        'duration': entry.get('duration'),
                        'thumbnail': None,
                    })
                return playlist_title, tracks
        except Exception as e:
            logger.error(f"Error extracting playlist: {e}")
            return None, []
