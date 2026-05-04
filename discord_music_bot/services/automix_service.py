from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Any, Tuple
import random
import logging

from discord_music_bot import consts
from discord_music_bot.repository import MusicRepository


logger = logging.getLogger("MusicBot.AutomixService")


@dataclass(frozen=True)
class AutomixConfig:
    recent_window: int = 15  # don't repeat very recent session plays
    top_limit: int = 50
    history_limit: int = 100
    max_penalty: int = 5
    top_map_limit: int = 300  # for history_explore play-count weights


class AutomixService:
    """
    Automix: два алгоритми + diversity (виключення недавніх automix-підборів).
    - top_weighted: зважена вибірка з топу історії (популярність), fallback у history.
    - history_explore: зважена вибірка з історії з ухилом у менш програні треки.
    """

    def __init__(self, repository: MusicRepository, config: AutomixConfig | None = None):
        self._repo = repository
        self._cfg = config or AutomixConfig()

    async def recommend_for_strategy(
        self,
        guild_id: int,
        strategy: str,
        *,
        recent_urls: List[str],
        automix_recent_urls: List[str],
        skip_penalties: Dict[str, int],
    ) -> Optional[Dict[str, Any]]:
        """
        Повертає трек з полями source=automix та automix_strategy (ефективний алгоритм A/B).
        """
        if strategy == consts.AUTOMIX_STRATEGY_HISTORY:
            track = await self._recommend_history_explore(
                guild_id,
                recent_urls=recent_urls,
                automix_recent_urls=automix_recent_urls,
                skip_penalties=skip_penalties,
            )
            if track:
                return self._tag(track, consts.AUTOMIX_STRATEGY_HISTORY)
            # fallback
            track = await self._recommend_top_weighted(
                guild_id,
                recent_urls=recent_urls,
                automix_recent_urls=automix_recent_urls,
                skip_penalties=skip_penalties,
            )
            if track:
                return self._tag(track, consts.AUTOMIX_STRATEGY_HISTORY)
            return None

        # top_weighted (default branch)
        track = await self._recommend_top_weighted(
            guild_id,
            recent_urls=recent_urls,
            automix_recent_urls=automix_recent_urls,
            skip_penalties=skip_penalties,
        )
        if track:
            return self._tag(track, consts.AUTOMIX_STRATEGY_TOP)
        track = await self._recommend_history_explore(
            guild_id,
            recent_urls=recent_urls,
            automix_recent_urls=automix_recent_urls,
            skip_penalties=skip_penalties,
        )
        if track:
            return self._tag(track, consts.AUTOMIX_STRATEGY_TOP)
        return None

    def _tag(self, t: Dict[str, Any], effective_strategy: str) -> Dict[str, Any]:
        out = dict(t)
        out["source"] = "automix"
        out["automix_strategy"] = effective_strategy
        return out

    def _blocked_urls(self, recent_urls: List[str], automix_recent_urls: List[str]) -> set:
        return {u for u in (recent_urls + automix_recent_urls) if u}

    async def _playcount_by_url(self, guild_id: int) -> Dict[str, int]:
        try:
            top = await self._repo.get_top_tracks(guild_id, limit=self._cfg.top_map_limit)
        except Exception as e:
            logger.warning(f"playcount map failed for {guild_id}: {e}")
            return {}
        out: Dict[str, int] = {}
        for t in top:
            u = t.get("url") or ""
            if u:
                out[u] = int(t.get("play_count") or 0)
        return out

    async def _recommend_top_weighted(
        self,
        guild_id: int,
        *,
        recent_urls: List[str],
        automix_recent_urls: List[str],
        skip_penalties: Dict[str, int],
    ) -> Optional[Dict[str, Any]]:
        blocked = self._blocked_urls(recent_urls, automix_recent_urls)
        try:
            top = await self._repo.get_top_tracks(guild_id, limit=self._cfg.top_limit)
        except Exception as e:
            logger.warning(f"Top tracks query failed for {guild_id}: {e}")
            top = []

        candidates: List[Tuple[Dict[str, Any], float]] = []
        for t in top:
            url = t.get("url") or ""
            if not url or url in blocked:
                continue
            play_count = int(t.get("play_count") or 0)
            if play_count <= 0:
                continue
            penalty = min(int(skip_penalties.get(url, 0)), self._cfg.max_penalty)
            weight = max(0.1, float(play_count) * (0.6**penalty))
            candidates.append((t, weight))

        picked = self._weighted_pick(candidates)
        if picked:
            return self._normalize_track(picked)

        try:
            history = await self._repo.get_history(guild_id, limit=self._cfg.history_limit)
        except Exception as e:
            logger.warning(f"History query failed for {guild_id}: {e}")
            history = []

        pool = self._unique_history_pool(history, blocked)
        if not pool:
            return None
        return self._normalize_track(random.choice(pool))

    async def _recommend_history_explore(
        self,
        guild_id: int,
        *,
        recent_urls: List[str],
        automix_recent_urls: List[str],
        skip_penalties: Dict[str, int],
    ) -> Optional[Dict[str, Any]]:
        blocked = self._blocked_urls(recent_urls, automix_recent_urls)
        play_map = await self._playcount_by_url(guild_id)

        try:
            history = await self._repo.get_history(guild_id, limit=self._cfg.history_limit)
        except Exception as e:
            logger.warning(f"History query failed for {guild_id}: {e}")
            history = []

        pool = self._unique_history_pool(history, blocked)
        if not pool:
            return None

        candidates: List[Tuple[Dict[str, Any], float]] = []
        for t in pool:
            url = t.get("url") or t.get("webpage_url") or ""
            pc = int(play_map.get(url, 0))
            penalty = min(int(skip_penalties.get(url, 0)), self._cfg.max_penalty)
            # Менше програні треки отримують більшу вагу (explore)
            explore = 1.0 / (1.0 + float(pc))
            weight = max(0.05, explore * (0.6**penalty))
            candidates.append((t, weight))

        picked = self._weighted_pick(candidates)
        if picked:
            return self._normalize_track(picked)
        return self._normalize_track(random.choice(pool))

    def _unique_history_pool(
        self, history: List[Dict[str, Any]], blocked: set
    ) -> List[Dict[str, Any]]:
        pool: List[Dict[str, Any]] = []
        seen: set = set()
        for t in history:
            url = t.get("url") or ""
            if not url or url in blocked or url in seen:
                continue
            seen.add(url)
            pool.append(t)
        return pool

    def _normalize_track(self, t: Dict[str, Any]) -> Dict[str, Any]:
        url = t.get("url") or t.get("webpage_url") or ""
        return {
            "title": t.get("title", "Unknown"),
            "url": url,
            "webpage_url": url,
            "duration": t.get("duration"),
            "thumbnail": t.get("thumbnail"),
            "requester": None,
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
