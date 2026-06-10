"""Shared yt-dlp configuration for CLI subprocesses and Python API."""

from __future__ import annotations

import base64
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_cookies_path: Optional[str] = None

YOUTUBE_PLAYER_CLIENTS = ["ios", "tv_embedded", "mweb", "web", "android"]
YOUTUBE_EXTRACTOR_ARGS = f"youtube:player_client={','.join(YOUTUBE_PLAYER_CLIENTS)}"


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


def build_ytdlp_cli_args(url: str, format_str: str) -> List[str]:
    """Build argv for a yt-dlp download-to-stdout subprocess."""
    args = [
        "yt-dlp",
        "--format",
        format_str,
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
