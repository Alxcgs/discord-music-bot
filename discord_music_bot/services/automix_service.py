from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Any, Tuple
import random
import logging
import inspect

from discord_music_bot import consts
from discord_music_bot.repository import MusicRepository


logger = logging.getLogger("MusicBot.AutomixService")


async def _maybe_await(value):
    if inspect.isawaitable(value):
        return await value
    return value


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

    @property
    def repository(self) -> MusicRepository:
        return self._repo

    async def recommend_for_strategy(
        self,
        guild_id: int,
        strategy: str,
        *,
        recent_urls: List[str] | None = None,
        automix_recent_urls: List[str] | None = None,
        skip_penalties: Dict[str, int] | None = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Повертає трек з полями source=automix та automix_strategy (ефективний алгоритм A/B).
        """
        recent_urls = recent_urls or []
        automix_recent_urls = automix_recent_urls or []
        skip_penalties = skip_penalties or {}

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

    def _get_diversity_penalty(self, index: int, penalties: List[int]) -> int:
        if not penalties:
            return 0
        if index < 0:
            return penalties[0]
        if index >= len(penalties):
            return penalties[-1]
        return penalties[index]

    async def _playcount_by_url(self, guild_id: int) -> Dict[str, int]:
        try:
            top = await _maybe_await(self._repo.get_top_tracks(guild_id, limit=self._cfg.top_map_limit))
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
        recent_urls: List[str] | None = None,
        automix_recent_urls: List[str] | None = None,
        skip_penalties: Dict[str, int] | None = None,
    ) -> Optional[Dict[str, Any]]:
        recent_urls = recent_urls or []
        automix_recent_urls = automix_recent_urls or []
        skip_penalties = skip_penalties or {}
        blocked = self._blocked_urls(recent_urls, automix_recent_urls)
        try:
            top = await _maybe_await(self._repo.get_top_tracks(guild_id, limit=self._cfg.top_limit))
            if not isinstance(top, list) and hasattr(self._repo, "get_top_tracks_for_automix"):
                top = await _maybe_await(self._repo.get_top_tracks_for_automix(guild_id, limit=self._cfg.top_limit))
            if not isinstance(top, list):
                top = []
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
            history = await _maybe_await(self._repo.get_history(guild_id, limit=self._cfg.history_limit))
            if not isinstance(history, list):
                history = []
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
        recent_urls: List[str] | None = None,
        automix_recent_urls: List[str] | None = None,
        skip_penalties: Dict[str, int] | None = None,
    ) -> Optional[Dict[str, Any]]:
        recent_urls = recent_urls or []
        automix_recent_urls = automix_recent_urls or []
        skip_penalties = skip_penalties or {}
        blocked = self._blocked_urls(recent_urls, automix_recent_urls)
        play_map = await self._playcount_by_url(guild_id)

        try:
            history = await _maybe_await(self._repo.get_history(guild_id, limit=self._cfg.history_limit))
            if not isinstance(history, list) and hasattr(self._repo, "get_history_for_automix"):
                history = await _maybe_await(self._repo.get_history_for_automix(guild_id, limit=self._cfg.history_limit))
            if not isinstance(history, list):
                history = []
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
