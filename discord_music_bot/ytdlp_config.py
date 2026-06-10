"""Shared yt-dlp configuration for CLI subprocesses and Python API."""

from __future__ import annotations

import base64
import logging
import os
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yt_dlp

logger = logging.getLogger(__name__)

_cookies_path: Optional[str] = None

# З cookies — web/tv клієнти; без — клієнти без PO-token вимог
YOUTUBE_PLAYER_CLIENTS_WITH_COOKIES = ["web", "mweb", "tv", "web_safari"]
YOUTUBE_PLAYER_CLIENTS_GUEST = ["android_vr", "tv_embedded", "ios", "mweb"]

YTDLP_AUDIO_FORMAT = "bestaudio/best"
YTDLP_FORMAT_FALLBACKS = (
    None,  # без селектора — вибір з formats вручну
    "bestaudio/best",
    "bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio/best",
    "ba/b",
    "best[height<=720]/best",
    "worst",
)


def init_ytdlp_cookies() -> Optional[str]:
    """Load YouTube cookies from env and return the file path, if configured."""
    global _cookies_path

    explicit_path = os.getenv("YTDLP_COOKIES_FILE", "").strip()
    if explicit_path and Path(explicit_path).is_file():
        _cookies_path = explicit_path
        logger.info("yt-dlp cookies loaded from YTDLP_COOKIES_FILE")
        _log_js_runtime()
        return _cookies_path

    cookies_b64 = os.getenv("YTDLP_COOKIES_B64", "").strip()
    if cookies_b64:
        data_dir = os.environ.get("DB_DATA_DIR", "data")
        os.makedirs(data_dir, exist_ok=True)
        cookies_path = os.path.join(data_dir, "ytdlp_cookies.txt")
        try:
            content = base64.b64decode(cookies_b64)
            with open(cookies_path, "wb") as f:
                f.write(content)
            _cookies_path = cookies_path
            logger.info("yt-dlp cookies loaded from YTDLP_COOKIES_B64")
            _log_js_runtime()
            return _cookies_path
        except Exception as exc:
            logger.error(f"Failed to decode YTDLP_COOKIES_B64: {exc}")
            return None

    logger.warning(
        "YouTube cookies not configured (YTDLP_COOKIES_B64 / YTDLP_COOKIES_FILE). "
        "Playback from cloud servers may fail with 'Sign in to confirm you're not a bot'."
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


def _player_clients() -> List[str]:
    if get_cookies_path():
        return YOUTUBE_PLAYER_CLIENTS_WITH_COOKIES
    return YOUTUBE_PLAYER_CLIENTS_GUEST


def apply_ytdlp_python_opts(opts: Dict[str, Any]) -> Dict[str, Any]:
    """Merge shared yt-dlp options into a YoutubeDL options dict."""
    merged = opts.copy()
    extractor_args = dict(merged.get("extractor_args") or {})
    extractor_args["youtube"] = {"player_client": _player_clients()}
    merged["extractor_args"] = extractor_args
    merged["remote_components"] = {"ejs:github"}

    cookies = get_cookies_path()
    if cookies:
        merged["cookiefile"] = cookies

    if shutil.which("node") and not shutil.which("deno"):
        merged["js_runtimes"] = {"node": {}}

    return merged


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


def extract_stream_url(page_url: str) -> Tuple[Optional[str], Dict[str, Any]]:
    """Resolve a direct media URL via yt-dlp API (format fallbacks + manual pick)."""
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

    for fmt in YTDLP_FORMAT_FALLBACKS:
        opts = dict(base_opts)
        if fmt:
            opts["format"] = fmt
        ydl_opts = apply_ytdlp_python_opts(opts)
        label = fmt or "manual-pick"
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
                    logger.info(f"Stream URL resolved with format '{label}'")
                    return stream_url, info
                n_formats = len(info.get("formats") or [])
                logger.warning(
                    f"yt-dlp extracted info but no playable URL (format '{label}', "
                    f"{n_formats} formats in list)"
                )
        except Exception as exc:
            last_error = exc
            logger.warning(f"yt-dlp format '{label}' failed: {exc}")

    if last_info:
        n = len(last_info.get("formats") or [])
        logger.error(
            f"Could not pick stream URL for {page_url} ({n} formats returned, "
            f"JS runtime: deno={bool(shutil.which('deno'))}, node={bool(shutil.which('node'))})"
        )
    elif last_error:
        logger.error(f"All yt-dlp format fallbacks failed for {page_url}: {last_error}")
    return None, {}


def build_ytdlp_cli_args(url: str, format_str: Optional[str] = None) -> List[str]:
    """Build argv for a yt-dlp download-to-stdout subprocess."""
    clients = ",".join(_player_clients())
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
        f"youtube:player_client={clients}",
    ]
    cookies = get_cookies_path()
    if cookies:
        args.extend(["--cookies", cookies])
    if shutil.which("node") and not shutil.which("deno"):
        args.extend(["--js-runtimes", "node"])
    args.append(url)
    return args
