import yt_dlp
import logging
import asyncio
from discord_music_bot import consts
from discord_music_bot.ytdlp_config import (
    apply_ytdlp_python_opts,
    fetch_piped_search,
    fetch_piped_stream,
    _piped_first_enabled,
)
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
        search_url = url if any(x in url.lower() for x in ['youtube.com', 'youtu.be', 'soundcloud.com']) else f"ytsearch:{url}"
        # SoundCloud потребує повної екстракції для отримання назв
        is_soundcloud = 'soundcloud.com' in url.lower()
        
        ydl_opts = apply_ytdlp_python_opts(self.light_ydl_opts.copy())
        if is_soundcloud:
            ydl_opts['extract_flat'] = False
            
        try:
            # Виконуємо синхронний код yt_dlp в окремому потоці
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = await self._get_loop().run_in_executor(None, lambda: ydl.extract_info(search_url, download=False))
                if not info:
                    return None
                
                # Якщо це пошук, беремо перший результат
                if 'entries' in info:
                    if not info['entries']:
                        return None
                    info = info['entries'][0]
                    
                return {
                    'title': info.get('title') or info.get('fulltitle') or 'Unknown',
                    'url': info.get('webpage_url', url) or info.get('url', url),
                    'duration': info.get('duration'),
                    'thumbnail': info.get('thumbnail')
                }
        except Exception as e:
            self.logger.error(f"Error extracting info for {url}: {e}")
            return None

    async def search_videos(self, query: str, max_results: int = 10) -> List[Dict[str, Any]]:
        """Шукає кілька відео за текстовим запитом (для меню вибору)."""

        # Спочатку пробуємо Piped /search — обхід блокування YouTube datacenter IP
        if _piped_first_enabled():
            try:
                piped_results = await self._get_loop().run_in_executor(
                    None, lambda: fetch_piped_search(query, max_results)
                )
                if piped_results:
                    return piped_results
                self.logger.warning("Piped search failed — falling back to yt-dlp ytsearch")
            except Exception as e:
                self.logger.warning(f"Piped search error: {e} — falling back to yt-dlp")

        # Fallback: yt-dlp ytsearch (може не працювати на cloud IP)
        search_url = f"ytsearch{max_results}:{query}"
        try:
            ydl_opts = apply_ytdlp_python_opts(self.light_ydl_opts.copy())
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = await self._get_loop().run_in_executor(None, lambda: ydl.extract_info(search_url, download=False))
                
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
                            'thumbnail': entry.get('thumbnail')
                        })
                if results:
                    return results
        except Exception as e:
            self.logger.warning(f"yt-dlp search failed for {query}: {e}")

        # Cloud host fallback: SoundCloud search (never blocked on datacenter IPs)
        self.logger.info(f"Falling back to SoundCloud search for '{query}'")
        try:
            sc_query = f"scsearch{max_results}:{query}"
            ydl_opts = {
                "quiet": True,
                "no_warnings": True,
                "extract_flat": True,
                "skip_download": True,
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = await self._get_loop().run_in_executor(
                    None, lambda: ydl.extract_info(sc_query, download=False)
                )
                if info and "entries" in info:
                    results = []
                    for entry in info["entries"]:
                        if entry:
                            results.append({
                                "title": entry.get("title", "Unknown"),
                                "url": entry.get("webpage_url", entry.get("url", "")),
                                "webpage_url": entry.get("webpage_url", entry.get("url", "")),
                                "duration": entry.get("duration"),
                                "thumbnail": entry.get("thumbnail"),
                            })
                    if results:
                        self.logger.info(f"SoundCloud search OK: {len(results)} results for '{query}'")
                        return results
        except Exception as sc_err:
            self.logger.error(f"SoundCloud search failed for '{query}': {sc_err}")

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
