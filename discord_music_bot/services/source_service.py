import yt_dlp
import logging
import asyncio
from discord_music_bot import consts
from discord_music_bot.ytdlp_config import apply_ytdlp_python_opts, _fetch_youtube_oembed_title, _youtube_video_id
from typing import List, Dict, Optional, Tuple, Any

class SourceService:
    """Сервіс для отримання метаданих пісень та плейлистів за допомогою yt-dlp."""

    def __init__(self, loop=None):
        self.logger = logging.getLogger('MusicBot.SourceService')
        self.light_ydl_opts = consts.YTDL_OPTIONS_LIGHT
        self._loop = loop

    def _get_loop(self):
        if self._loop:
            return self._loop
        try:
            return asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.get_event_loop()

    async def get_video_info(self, url: str) -> Optional[Dict[str, Any]]:
        """Отримує метадані для одного відео/треку за URL або запитом."""
        is_yt = any(x in url.lower() for x in ['youtube.com', 'youtu.be'])
        search_url = url if is_yt or 'soundcloud.com' in url.lower() else f"ytsearch:{url}"
        is_soundcloud = 'soundcloud.com' in url.lower()

        ydl_opts = apply_ytdlp_python_opts(self.light_ydl_opts.copy())
        if is_soundcloud:
            ydl_opts['extract_flat'] = False

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = await self._get_loop().run_in_executor(None, lambda: ydl.extract_info(search_url, download=False))
                if info:
                    if 'entries' in info:
                        if info['entries']:
                            info = info['entries'][0]
                        else:
                            info = None

                if info:
                    return {
                        'title': info.get('title') or info.get('fulltitle') or 'Unknown',
                        'url': info.get('webpage_url', url) or info.get('url', url),
                        'duration': info.get('duration'),
                        'thumbnail': info.get('thumbnail')
                    }
        except Exception as e:
            self.logger.warning(f"yt-dlp extract_info failed for {url}: {e}")

        # Якщо вилучення прямих метаданих через YouTube впало через bot-check, використовуємо oEmbed
        if is_yt or _youtube_video_id(url):
            v_id = _youtube_video_id(url)
            oembed_title = _fetch_youtube_oembed_title(url)
            if oembed_title:
                self.logger.info(f"Retrieved metadata via oEmbed for {url}: '{oembed_title}'")
                return {
                    'title': oembed_title,
                    'url': url,
                    'webpage_url': url,
                    'duration': None,
                    'thumbnail': f"https://img.youtube.com/vi/{v_id}/hqdefault.jpg" if v_id else None
                }

        return None

    async def search_videos(self, query: str, max_results: int = 10) -> List[Dict[str, Any]]:
        """Шукає кілька відео за текстовим запитом (для меню вибору)."""
        search_url = f"ytsearch{max_results}:{query}"

        try:
            ydl_opts = apply_ytdlp_python_opts(self.light_ydl_opts.copy())
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = await self._get_loop().run_in_executor(None, lambda: ydl.extract_info(search_url, download=False))

                if info and 'entries' in info and info['entries']:
                    results = []
                    for entry in info['entries']:
                        if entry:
                            results.append({
                                'title': entry.get('title', 'Unknown'),
                                'url': entry.get('webpage_url', entry.get('url', '')),
                                'webpage_url': entry.get('webpage_url', entry.get('url', '')),
                                'duration': entry.get('duration'),
                                'thumbnail': entry.get('thumbnail')
                            })
                    if results:
                        return results
        except Exception as e:
            self.logger.warning(f"YouTube search failed for '{query}': {e}")

        # Якщо YouTube пошук заблокировано хмарою, пробуємо SoundCloud пошук для меню
        try:
            sc_search_url = f"scsearch{max_results}:{query}"
            sc_opts = {'quiet': True, 'no_warnings': True, 'extract_flat': True}
            with yt_dlp.YoutubeDL(sc_opts) as ydl:
                sc_info = await self._get_loop().run_in_executor(None, lambda: ydl.extract_info(sc_search_url, download=False))
                if sc_info and 'entries' in sc_info:
                    results = []
                    for entry in sc_info['entries']:
                        if entry:
                            u = entry.get('url') or entry.get('webpage_url', '')
                            if not u.startswith('http'):
                                u = f"https://soundcloud.com/{u}"
                            results.append({
                                'title': entry.get('title', 'Unknown'),
                                'url': u,
                                'webpage_url': u,
                                'duration': entry.get('duration'),
                                'thumbnail': entry.get('thumbnail')
                            })
                    return results
        except Exception as exc:
            self.logger.warning(f"SoundCloud fallback search failed for '{query}': {exc}")

        return []

    async def extract_playlist(self, url: str) -> Tuple[Optional[str], List[Dict[str, Any]]]:
        """Витягує список треків з плейлиста (тільки метадані, швидко)."""
        # SoundCloud не підтримує extract_flat — використовуємо повну екстракцію
        is_soundcloud = 'soundcloud.com' in url.lower()
        
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False if is_soundcloud else 'in_playlist',
            'skip_download': True,
            'ignoreerrors': True,
        }
        
        try:
            ydl_opts = apply_ytdlp_python_opts(ydl_opts)
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = await self._get_loop().run_in_executor(None, lambda: ydl.extract_info(url, download=False))
                
                if not info or 'entries' not in info:
                    return None, []

                playlist_title = info.get('title', 'Плейлист')
                tracks = []
                
                for entry in info['entries']:
                    if not entry:
                        continue
                        
                    track_url = entry.get('url') or entry.get('webpage_url', '')
                    if not track_url:
                        continue
                        
                    # Для flat extraction URL може бути ID — конвертуємо у повний URL
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
            self.logger.error(f"Error extracting playlist {url}: {e}")
            return None, []
