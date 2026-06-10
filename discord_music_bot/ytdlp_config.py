"""Shared yt-dlp configuration for CLI subprocesses and Python API."""

from __future__ import annotations

import base64
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yt_dlp

logger = logging.getLogger(__name__)

_cookies_path: Optional[str] = None

YOUTUBE_PLAYER_CLIENTS = ["ios", "tv_embedded", "mweb", "web", "android"]
YOUTUBE_EXTRACTOR_ARGS = f"youtube:player_client={','.join(YOUTUBE_PLAYER_CLIENTS)}"

# FFmpeg decodes any container — try several selectors until one works.
YTDLP_AUDIO_FORMAT = "bestaudio/best"
YTDLP_FORMAT_FALLBACKS = (
    "bestaudio/best",
    "bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio/best",
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
            return _cookies_path
        except Exception as exc:
            logger.error(f"Failed to decode YTDLP_COOKIES_B64: {exc}")
            return None

    logger.warning(
        "YouTube cookies not configured (YTDLP_COOKIES_B64 / YTDLP_COOKIES_FILE). "
        "Playback from cloud servers may fail with 'Sign in to confirm you're not a bot'."
    )
    return None


def get_cookies_path() -> Optional[str]:
    return _cookies_path


def apply_ytdlp_python_opts(opts: Dict[str, Any]) -> Dict[str, Any]:
    """Merge shared yt-dlp options into a YoutubeDL options dict."""
    merged = opts.copy()
    extractor_args = dict(merged.get("extractor_args") or {})
    extractor_args["youtube"] = {"player_client": YOUTUBE_PLAYER_CLIENTS}
    merged["extractor_args"] = extractor_args

    cookies = get_cookies_path()
    if cookies:
        merged["cookiefile"] = cookies
    return merged


def extract_stream_url(page_url: str) -> Tuple[Optional[str], Dict[str, Any]]:
    """Resolve a direct media URL via yt-dlp API (format fallbacks)."""
    base_opts: Dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "source_address": "0.0.0.0",
        "force-ipv4": True,
        "cachedir": False,
    }
    last_error: Optional[Exception] = None

    for fmt in YTDLP_FORMAT_FALLBACKS:
        ydl_opts = apply_ytdlp_python_opts({**base_opts, "format": fmt})
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
                stream_url = info.get("url")
                if stream_url:
                    logger.info(f"Stream URL resolved with format '{fmt}'")
                    return stream_url, info
        except Exception as exc:
            last_error = exc
            logger.warning(f"yt-dlp format '{fmt}' failed: {exc}")

    if last_error:
        logger.error(f"All yt-dlp format fallbacks failed for {page_url}: {last_error}")
    return None, {}


def build_ytdlp_cli_args(url: str, format_str: Optional[str] = None) -> List[str]:
    """Build argv for a yt-dlp download-to-stdout subprocess."""
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
        "--extractor-args",
        YOUTUBE_EXTRACTOR_ARGS,
    ]
    cookies = get_cookies_path()
    if cookies:
        args.extend(["--cookies", cookies])
    args.append(url)
    return args
