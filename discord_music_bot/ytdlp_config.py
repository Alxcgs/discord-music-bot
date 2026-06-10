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
    "https://pipedapi.kavin.rocks",
    "https://pipedapi.adminforge.de",
    "https://api.piped.private.coffee",
    "https://pipedapi.in.projectsegfau.lt",
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


def fetch_piped_stream(page_url: str) -> Tuple[Optional[str], Dict[str, Any]]:
    """Fallback: отримати audio URL через Piped API (не залежить від IP Render)."""
    video_id = _youtube_video_id(page_url)
    if not video_id:
        return None, {}

    instances: List[str] = []
    custom = os.getenv("PIPED_API_URL", "").strip().rstrip("/")
    if custom:
        instances.append(custom)
    instances.extend(PIPED_INSTANCES)

    headers = {"User-Agent": "Mozilla/5.0 (compatible; discord-music-bot/1.0)"}

    for base in instances:
        api_url = f"{base}/streams/{video_id}"
        try:
            req = Request(api_url, headers=headers)
            with urlopen(req, timeout=20) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            meta: Dict[str, Any] = {
                "title": data.get("title"),
                "webpage_url": page_url,
                "duration": data.get("duration"),
                "thumbnail": data.get("thumbnailUrl"),
            }

            audio_streams = data.get("audioStreams") or []
            if not audio_streams:
                logger.warning(f"Piped ({base}): no audio streams for {video_id}")
                continue

            def _stream_score(stream: Dict[str, Any]) -> int:
                mime = (stream.get("mimeType") or "").lower()
                opus_bonus = 100_000 if "opus" in mime else 0
                return opus_bonus + int(stream.get("bitrate", 0) or 0)

            audio_streams.sort(key=_stream_score, reverse=True)
            stream_url = audio_streams[0].get("url")
            if stream_url:
                logger.info(f"Stream URL resolved via Piped ({base})")
                return stream_url, meta
        except (URLError, TimeoutError, json.JSONDecodeError, KeyError) as exc:
            logger.warning(f"Piped instance {base} failed: {exc}")
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
    """Resolve a direct media URL via yt-dlp (profiles × format fallbacks)."""
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
    if not get_cookies_path():
        profiles = [p for p in profiles if not p[1]]

    for profile_name, use_cookies, clients in profiles:
        if use_cookies and not get_cookies_path():
            continue

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
                    n_formats = len(info.get("formats") or [])
                    logger.warning(
                        f"Profile '{profile_name}' / '{fmt_label}': "
                        f"no playable URL ({n_formats} formats)"
                    )
            except Exception as exc:
                last_error = exc
                if _is_bot_check_error(exc):
                    logger.warning(
                        f"Profile '{profile_name}' bot-check — trying next profile"
                    )
                    break
                logger.warning(
                    f"Profile '{profile_name}' / '{fmt_label}' failed: {exc}"
                )

    if _youtube_video_id(page_url):
        logger.info("yt-dlp exhausted for YouTube — trying Piped API fallback")
        piped_url, piped_meta = fetch_piped_stream(page_url)
        if piped_url:
            return piped_url, piped_meta

    if last_info:
        n = len(last_info.get("formats") or [])
        logger.error(
            f"Could not pick stream URL for {page_url} ({n} formats in last response)"
        )
    elif last_error:
        logger.error(f"All yt-dlp profiles failed for {page_url}: {last_error}")
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
