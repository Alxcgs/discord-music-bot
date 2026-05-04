from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Any, Tuple
import random
import logging

from discord_music_bot.repository import MusicRepository


logger = logging.getLogger("MusicBot.AutomixService")


@dataclass(frozen=True)
class AutomixConfig:
    recent_window: int = 15  # don't repeat very recent tracks
    top_limit: int = 50      # how many top tracks to consider
    history_limit: int = 100 # fallback pool size
    max_penalty: int = 5     # cap skip penalty impact


class AutomixService:
    """
    Minimal Automix recommender.
    - Uses guild's historical listening data.
    - Penalizes tracks the guild recently skipped when they were recommended by Automix.
    """

    def __init__(self, repository: MusicRepository, config: AutomixConfig | None = None):
        self._repo = repository
        self._cfg = config or AutomixConfig()

    async def recommend_next(
        self,
        guild_id: int,
        *,
        recent_urls: List[str],
        skip_penalties: Dict[str, int],
    ) -> Optional[Dict[str, Any]]:
        """
        Returns a track dict {title,url,webpage_url,duration,thumbnail,source}
        or None if no recommendation is possible.
        """
        recent_set = set([u for u in recent_urls if u])

        # 1) Prefer weighted sampling from top tracks (collab-ish within guild).
        try:
            top = await self._repo.get_top_tracks(guild_id, limit=self._cfg.top_limit)
        except Exception as e:
            logger.warning(f"Top tracks query failed for {guild_id}: {e}")
            top = []

        candidates: List[Tuple[Dict[str, Any], float]] = []
        for t in top:
            url = t.get("url") or ""
            if not url or url in recent_set:
                continue
            play_count = int(t.get("play_count") or 0)
            if play_count <= 0:
                continue
            penalty = min(int(skip_penalties.get(url, 0)), self._cfg.max_penalty)
            weight = max(0.1, float(play_count) * (0.6 ** penalty))
            candidates.append((t, weight))

        picked = self._weighted_pick(candidates)
        if picked:
            return self._normalize_track(picked, source="automix")

        # 2) Fallback: sample from history (unique-ish), avoiding recent.
        try:
            history = await self._repo.get_history(guild_id, limit=self._cfg.history_limit)
        except Exception as e:
            logger.warning(f"History query failed for {guild_id}: {e}")
            history = []

        pool = []
        seen = set()
        for t in history:
            url = t.get("url") or ""
            if not url or url in recent_set:
                continue
            if url in seen:
                continue
            seen.add(url)
            pool.append(t)

        if not pool:
            return None

        chosen = random.choice(pool)
        return self._normalize_track(chosen, source="automix")

    def _normalize_track(self, t: Dict[str, Any], *, source: str) -> Dict[str, Any]:
        url = t.get("url") or t.get("webpage_url") or ""
        return {
            "title": t.get("title", "Unknown"),
            "url": url,
            "webpage_url": url,
            "duration": t.get("duration"),
            "thumbnail": t.get("thumbnail"),
            "requester": None,
            "source": source,
        }

    def _weighted_pick(self, items: List[Tuple[Dict[str, Any], float]]) -> Optional[Dict[str, Any]]:
        if not items:
            return None
        total = sum(w for _, w in items if w > 0)
        if total <= 0:
            return None
        r = random.random() * total
        upto = 0.0
        for item, w in items:
            if w <= 0:
                continue
            upto += w
            if upto >= r:
                return item
        return items[-1][0]
