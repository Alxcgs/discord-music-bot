"""Shared yt-dlp configuration for CLI subprocesses and Python API."""

from __future__ import annotations

import base64
import json
import logging
import os
import re
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.error import URLError
from urllib.request import Request, urlopen

import yt_dlp

logger = logging.getLogger(__name__)

_cookies_path: Optional[str] = None

# Профілі: спочатку без cookies (Deno + tv_embedded/android_vr), потім з cookies
EXTRACTION_PROFILES: Tuple[Tuple[str, bool, List[str]], ...] = (
    ("guest-android_vr", False, ["android_vr", "tv_embedded"]),
    ("guest-ios", False, ["ios", "mweb"]),
    ("guest-web", False, ["mweb", "web"]),
    ("cookies-tv", True, ["tv_embedded", "tv", "web"]),
    ("cookies-web", True, ["web", "mweb", "web_safari"]),
)

YTDLP_AUDIO_FORMAT = "bestaudio/best"
YTDLP_FORMAT_FALLBACKS = (
    None,
    "bestaudio/best",
    "ba/b",
    "worst",
)

# Публічні Piped API — обхід блокування YouTube з datacenter IP (Render тощо)
PIPED_INSTANCES = (
    "https://pipedapi.adminforge.de",
    "https://pipedapi.astral.cy",
    "https://api.piped.privacydev.net",
    "https://pipedapi.mha.fi",
    "https://pipedapi.kavin.rocks",
    "https://api.piped.projectsegfau.lt",
    "https://pipedapi.lunar.icu",
    "https://pipedapi.smnz.de",
    "https://piped-api.garudalinux.org",
    "https://api.piped.private.coffee",
)


def _write_cookies_file(cookies_path: str, raw_bytes: bytes) -> None:
    """Write Netscape cookies with Unix line endings (CRLF з Windows ламає yt-dlp на Linux)."""
    text = raw_bytes.decode("utf-8", errors="replace")
    if text.startswith("\ufeff"):
        text = text[1:]
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if "# Netscape HTTP Cookie File" not in text:
        logger.warning("Cookies file may be invalid — missing Netscape header")
    with open(cookies_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def _log_cookie_stats(path: str) -> None:
    try:
        with open(path, encoding="utf-8") as f:
            entries = [
                line
                for line in f
                if line.strip() and not line.startswith("#")
            ]
        yt_entries = [e for e in entries if "youtube.com" in e]
        logger.info(
            f"yt-dlp cookies file: {len(yt_entries)} youtube.com entries "
            f"({len(entries)} total)"
        )
        if len(yt_entries) < 3:
            logger.warning(
                "Very few YouTube cookies — re-export from browser while logged in"
            )
    except Exception as exc:
        logger.warning(f"Could not read cookie stats: {exc}")


def init_ytdlp_cookies() -> Optional[str]:
    """Load YouTube cookies from env and return the file path, if configured."""
    global _cookies_path

    explicit_path = os.getenv("YTDLP_COOKIES_FILE", "").strip()
    if explicit_path and Path(explicit_path).is_file():
        _cookies_path = explicit_path
        logger.info("yt-dlp cookies loaded from YTDLP_COOKIES_FILE")
        _log_cookie_stats(_cookies_path)
        _log_js_runtime()
        return _cookies_path

    cookies_b64 = os.getenv("YTDLP_COOKIES_B64", "").strip()
    if cookies_b64:
        data_dir = os.environ.get("DB_DATA_DIR", "data")
        os.makedirs(data_dir, exist_ok=True)
        cookies_path = os.path.join(data_dir, "ytdlp_cookies.txt")
        try:
            content = base64.b64decode(cookies_b64)
            _write_cookies_file(cookies_path, content)
            _cookies_path = cookies_path
            logger.info("yt-dlp cookies loaded from YTDLP_COOKIES_B64")
            _log_cookie_stats(cookies_path)
            _log_js_runtime()
            return _cookies_path
        except Exception as exc:
            logger.error(f"Failed to decode YTDLP_COOKIES_B64: {exc}")
            return None

    logger.warning(
        "YouTube cookies not configured (YTDLP_COOKIES_B64 / YTDLP_COOKIES_FILE). "
        "Will try guest player clients with Deno."
    )
    _log_js_runtime()
    return None


def _log_js_runtime() -> None:
    deno = shutil.which("deno")
    node = shutil.which("node")
    if deno:
        logger.info(f"yt-dlp JS runtime: deno ({deno})")
    elif node:
        logger.info(f"yt-dlp JS runtime: node ({node})")
    else:
        logger.warning(
            "No deno/node JS runtime found — YouTube format extraction will likely fail. "
            "See https://github.com/yt-dlp/yt-dlp/wiki/EJS"
        )


def get_cookies_path() -> Optional[str]:
    return _cookies_path


def apply_ytdlp_python_opts(
    opts: Dict[str, Any],
    *,
    use_cookies: bool = True,
    player_clients: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Merge shared yt-dlp options into a YoutubeDL options dict."""
    merged = opts.copy()
    clients = player_clients or EXTRACTION_PROFILES[0][2]
    extractor_args = dict(merged.get("extractor_args") or {})
    extractor_args["youtube"] = {"player_client": clients}
    merged["extractor_args"] = extractor_args
    merged["remote_components"] = {"ejs:github"}

    merged.pop("cookiefile", None)
    if use_cookies:
        cookies = get_cookies_path()
        if cookies:
            merged["cookiefile"] = cookies

    if shutil.which("node") and not shutil.which("deno"):
        merged["js_runtimes"] = {"node": {}}

    proxy = os.getenv("YTDLP_PROXY", "").strip()
    if proxy:
        merged["proxy"] = proxy

    return merged


def _youtube_video_id(url: str) -> Optional[str]:
    if not url:
        return None
    match = re.search(
        r"(?:youtube\.com/watch\?.*v=|youtu\.be/|youtube\.com/embed/)([A-Za-z0-9_-]{11})",
        url,
    )
    return match.group(1) if match else None


def _piped_first_enabled() -> bool:
    return os.getenv("YTDLP_PIPED_FIRST", "1").strip().lower() not in ("0", "false", "no")


def _pick_piped_stream_url(data: Dict[str, Any]) -> Optional[str]:
    """Pick best playable URL from a Piped /streams response."""
    audio_streams = list(data.get("audioStreams") or [])
    if audio_streams:

        def _audio_score(stream: Dict[str, Any]) -> int:
            mime = (stream.get("mimeType") or "").lower()
            opus_bonus = 100_000 if "opus" in mime else 0
            return opus_bonus + int(stream.get("bitrate", 0) or 0)

        audio_streams.sort(key=_audio_score, reverse=True)
        url = audio_streams[0].get("url")
        if url:
            return url

    video_streams = list(data.get("videoStreams") or [])
    combined = [
        s for s in video_streams
        if s.get("url") and not s.get("videoOnly", False)
    ]
    if combined:
        combined.sort(key=lambda s: int(s.get("bitrate", 0) or 0), reverse=True)
        return combined[0].get("url")

    hls = data.get("hls")
    if isinstance(hls, str) and hls.startswith("http"):
        return hls

    return None


def fetch_piped_stream(page_url: str) -> Tuple[Optional[str], Dict[str, Any]]:
    """Отримати media URL через Piped API (якщо вказано кастомну PIPED_API_URL)."""
    video_id = _youtube_video_id(page_url)
    if not video_id:
        return None, {}

    custom = os.getenv("PIPED_API_URL", "").strip().rstrip("/")
    if not custom:
        # Пропускаємо публічні Piped інстанси, оскільки вони неробочі та викликають затримки
        return None, {}

    instances = [custom]
    headers = {"User-Agent": "Mozilla/5.0 (compatible; discord-music-bot/1.0)"}

    for base in instances:
        api_url = f"{base}/streams/{video_id}"
        try:
            req = Request(api_url, headers=headers)
            with urlopen(req, timeout=2.5) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            meta: Dict[str, Any] = {
                "title": data.get("title"),
                "webpage_url": page_url,
                "duration": data.get("duration"),
                "thumbnail": data.get("thumbnailUrl"),
            }

            stream_url = _pick_stream_url(data)
            if stream_url:
                logger.info(f"Stream URL resolved via Piped ({base})")
                return stream_url, meta
        except Exception as exc:
            logger.warning(f"Piped instance {base} failed: {exc}")

    return None, {}


def _pick_stream_url(info: Dict[str, Any]) -> Optional[str]:
    """Pick a playable URL from extracted info / formats list."""
    if info.get("url"):
        return info["url"]

    formats = info.get("formats") or []
    if not formats:
        return None

    audio_only = [
        f
        for f in formats
        if f.get("url") and f.get("vcodec") == "none" and f.get("acodec") not in (None, "none")
    ]
    audio_only.sort(key=lambda f: (f.get("abr") or 0, f.get("tbr") or 0), reverse=True)
    if audio_only:
        return audio_only[0]["url"]

    with_audio = [
        f for f in formats if f.get("url") and f.get("acodec") not in (None, "none")
    ]
    with_audio.sort(key=lambda f: f.get("height") or 9999)
    if with_audio:
        return with_audio[0]["url"]

    return None


def _is_bot_check_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return "sign in to confirm" in msg or "not a bot" in msg


def extract_stream_url(page_url: str) -> Tuple[Optional[str], Dict[str, Any]]:
    """Resolve a direct media URL without requiring user accounts or cookies: Deno guest profiles -> YouTube Search -> SoundCloud fallback."""
    video_id = _youtube_video_id(page_url)
    cookies = get_cookies_path()

    if video_id and _piped_first_enabled():
        piped_url, piped_meta = fetch_piped_stream(page_url)
        if piped_url:
            return piped_url, piped_meta

    base_opts: Dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "source_address": "0.0.0.0",
        "force-ipv4": True,
        "cachedir": False,
    }
    last_error: Optional[Exception] = None
    last_info: Dict[str, Any] = {}

    profiles = list(EXTRACTION_PROFILES)
    if not cookies:
        profiles = [p for p in profiles if not p[1]]

    bot_check_triggered = False
    for profile_name, use_cookies, clients in profiles:
        if use_cookies and not cookies:
            continue
        if bot_check_triggered:
            break

        for fmt in YTDLP_FORMAT_FALLBACKS:
            opts = dict(base_opts)
            if fmt:
                opts["format"] = fmt
            ydl_opts = apply_ytdlp_python_opts(
                opts, use_cookies=use_cookies, player_clients=clients
            )
            fmt_label = fmt or "manual-pick"
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(page_url, download=False)
                    if not info:
                        continue
                    if "entries" in info:
                        entries = info.get("entries") or []
                        if not entries:
                            continue
                        info = entries[0]
                    last_info = info
                    stream_url = _pick_stream_url(info)
                    if stream_url:
                        logger.info(
                            f"Stream URL resolved (profile={profile_name}, format={fmt_label})"
                        )
                        return stream_url, info
            except Exception as exc:
                last_error = exc
                if _is_bot_check_error(exc):
                    logger.warning(
                        f"Profile '{profile_name}' bot-check — cloud IP restriction detected"
                    )
                    if not cookies:
                        bot_check_triggered = True
                        break
                    break
                logger.warning(
                    f"Profile '{profile_name}' / '{fmt_label}' failed: {exc}"
                )

    # Резервний ланцюжок переходу для YouTube джерел (тільки YouTube пошук)
    fallback_query = None
    if last_info and last_info.get("title"):
        fallback_query = last_info.get("title")
    elif video_id:
        fallback_query = _fetch_youtube_oembed_title(page_url) or page_url
    else:
        fallback_query = page_url

    if fallback_query:
        ytm_url, ytm_meta = _try_youtube_music_fallback(fallback_query)
        if ytm_url:
            return ytm_url, ytm_meta

        # SoundCloud резерв ТОЛЬКО для не-YouTube джерел
        if not video_id:
            sc_url, sc_meta = _try_soundcloud_fallback(fallback_query)
            if sc_url:
                return sc_url, sc_meta

    if last_info:
        n = len(last_info.get("formats") or [])
        logger.error(
            f"Could not pick stream URL for {page_url} ({n} formats in last response)"
        )
    elif last_error:
        logger.error(f"All yt-dlp profiles failed for {page_url}: {last_error}")
    return None, {}


def _fetch_youtube_oembed_title(page_url: str) -> Optional[str]:
    """Отримати назву відео через відкритий YouTube oEmbed API."""
    video_id = _youtube_video_id(page_url)
    if not video_id:
        return None
    oembed_url = f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={video_id}&format=json"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    try:
        req = Request(oembed_url, headers=headers)
        with urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            title = data.get("title")
            if title:
                logger.info(f"Resolved YouTube title via oEmbed: '{title}'")
                return title
    except Exception as exc:
        logger.debug(f"oEmbed fetch failed for {video_id}: {exc}")
    return None


def _clean_title_for_search(title: str) -> str:
    """Очищає назву відео від рекламних/технічних дужок для точного пошуку треку."""
    if not title:
        return ""
    cleaned = re.sub(
        r"[\(\[\{](?:official|music|video|audio|clip|премьера|клип|официальный|lyric|hd|4k|remastered|full|mv).*?[\)\]\}]",
        "",
        title,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"(?i)\b(official music video|official video|music video|lyric video|премьера клипа|официальный клип)\b",
        "",
        cleaned,
    )
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned or title


def _try_youtube_music_fallback(query: str) -> Tuple[Optional[str], Dict[str, Any]]:
    """Пошук та відтворення через YouTube Search (ytsearch1) з альтернативними аудіо-клієнтами."""
    if not query:
        return None, {}
    cleaned = _clean_title_for_search(query)
    logger.info(f"Attempting YouTube Search fallback for: '{cleaned}'")
    ytm_opts = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "format": "bestaudio/best",
        "default_search": "ytsearch1",
        "extractor_args": {"youtube": {"player_client": ["android_music", "mweb", "web"]}},
    }
    ytm_target = f"ytsearch1:{cleaned}" if not cleaned.startswith("ytsearch") and not cleaned.startswith("http") else cleaned
    try:
        with yt_dlp.YoutubeDL(ytm_opts) as ydl:
            info = ydl.extract_info(ytm_target, download=False)
            if not info:
                return None, {}
            if "entries" in info:
                entries = [e for e in (info.get("entries") or []) if e]
                if not entries:
                    return None, {}
                info = entries[0]
            stream_url = _pick_stream_url(info)
            if stream_url:
                logger.info(f"Stream URL resolved via YouTube Search fallback: '{info.get('title')}'")
                return stream_url, info
    except Exception as exc:
        logger.warning(f"YouTube Search fallback failed: {exc}")
    return None, {}


def _score_soundcloud_entry(entry: Dict[str, Any], original_query: str) -> int:
    """Точне ранжування кандидатів: вимагає обов'язкової наявності виконавця та назви треку."""
    title = (entry.get("title") or "").lower()
    uploader = (entry.get("uploader") or entry.get("channel") or "").lower()
    url = (entry.get("url") or entry.get("webpage_url") or "").lower()
    full_text = f"{title} {uploader} {url}"
    q = original_query.lower()

    # Якщо у запиті є структура "Artist - Song", перевіряємо наявність виконавця
    parts = re.split(r"\s*-\s*|\s+by\s+", q, maxsplit=1)
    if len(parts) == 2:
        artist, song = parts[0].strip(), parts[1].strip()
        artist_words = [w for w in re.findall(r"\w+", artist) if len(w) >= 3]
        song_words = [w for w in re.findall(r"\w+", song) if len(w) >= 3]

        # Якщо виконавець є у запиті, але відсутній у назві/авторі/URL кандидата — ВІДКИДАЄМО (-1000)
        if artist_words and not any(aw in full_text for aw in artist_words):
            return -1000

        # Якщо пісня має ключові слова, але жодне з них не збіглося — ВІДКИДАЄМО (-1000)
        if song_words and not any(sw in full_text for sw in song_words):
            return -1000
    else:
        words = [w for w in re.findall(r"\w+", q) if len(w) >= 3]
        if words and not any(w in full_text for w in words):
            return -1000

    score = 100
    unwanted = ["slowed", "remix", "nightcore", "reverb", "speed up", "sped up", "edit", "bass boosted", "8d"]
    for kw in unwanted:
        if kw in title and kw not in q:
            score -= 50

    if q and q in title:
        score += 40

    return score


def _try_soundcloud_fallback(query: str) -> Tuple[Optional[str], Dict[str, Any]]:
    """Резервний пошук та відтворення через SoundCloud з extract_flat і фільтрацією DRM."""
    if not query:
        return None, {}

    cleaned_query = _clean_title_for_search(query)
    logger.info(f"Attempting SoundCloud fallback search for: '{cleaned_query}' (raw: '{query}')")

    sc_opts = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "format": "bestaudio/best",
        "default_search": "scsearch10",
        "extract_flat": True,  # Не викликає deep format resolution на списку кандидатів (запобігає фатальній помилці DRM)
    }
    sc_target = f"scsearch10:{cleaned_query}" if not cleaned_query.startswith("scsearch") and not cleaned_query.startswith("http") else cleaned_query
    try:
        with yt_dlp.YoutubeDL(sc_opts) as ydl:
            info = ydl.extract_info(sc_target, download=False)
            if not info:
                return None, {}
            entries = []
            if "entries" in info:
                entries = [e for e in (info.get("entries") or []) if e]
            elif info.get("url"):
                entries = [info]

            if not entries:
                return None, {}

            # Сортуємо кандидатів за відповідністю та відсіюємо невідповідні (-1000)
            valid_candidates = [e for e in entries if _score_soundcloud_entry(e, cleaned_query) > 0]
            if not valid_candidates:
                logger.warning(f"No strictly matching SoundCloud candidates found for '{cleaned_query}' — skipping wrong track playback")
                return None, {}

            valid_candidates.sort(key=lambda e: _score_soundcloud_entry(e, cleaned_query), reverse=True)

            # Перебираємо кандидатів по одному через окремий YoutubeDL екземпляр
            deep_opts = {
                "quiet": True,
                "no_warnings": True,
                "noplaylist": True,
                "format": "bestaudio/best",
            }
            with yt_dlp.YoutubeDL(deep_opts) as deep_ydl:
                for candidate in valid_candidates:
                    cand_title = candidate.get("title") or "Unknown track"
                    try:
                        cand_url = candidate.get("url") or candidate.get("webpage_url")
                        if not cand_url:
                            continue
                        if not cand_url.startswith("http"):
                            cand_url = f"https://soundcloud.com/{cand_url}"
                        cand_info = deep_ydl.extract_info(cand_url, download=False)
                        if not cand_info:
                            continue
                        stream_url = _pick_stream_url(cand_info)
                        if stream_url:
                            logger.info(f"Stream URL resolved via SoundCloud fallback: '{cand_info.get('title', cand_title)}'")
                            return stream_url, cand_info
                    except Exception as exc:
                        logger.warning(f"SoundCloud candidate '{cand_title}' skipped (DRM / unavailable): {exc}")
                        continue

    except Exception as exc:
        logger.warning(f"SoundCloud fallback search failed: {exc}")
    return None, {}



def build_ytdlp_cli_args(url: str, format_str: Optional[str] = None) -> List[str]:
    """Build argv for a yt-dlp download-to-stdout subprocess."""
    _, _, clients = EXTRACTION_PROFILES[0]
    args = [
        "yt-dlp",
        "--format",
        format_str or YTDLP_AUDIO_FORMAT,
        "--output",
        "-",
        "--no-warnings",
        "--retries",
        "3",
        "--fragment-retries",
        "3",
        "--remote-components",
        "ejs:github",
        "--extractor-args",
        f"youtube:player_client={','.join(clients)}",
    ]
    cookies = get_cookies_path()
    if cookies:
        args.extend(["--cookies", cookies])
    if shutil.which("node") and not shutil.which("deno"):
        args.extend(["--js-runtimes", "node"])
    args.append(url)
    return args
