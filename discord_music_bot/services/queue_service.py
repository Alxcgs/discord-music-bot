from typing import List, Dict, Optional, Any
import random
from discord_music_bot import consts

class QueueService:
    def __init__(self):
        self._queues: Dict[int, List[Dict[str, Any]]] = {}
        self._history: Dict[int, List[Dict[str, Any]]] = {}

    def get_queue(self, guild_id: int) -> List[Dict[str, Any]]:
        if guild_id not in self._queues:
            self._queues[guild_id] = []
        return self._queues[guild_id]

    def add_track(self, guild_id: int, track: Dict[str, Any]) -> None:
        if guild_id not in self._queues:
            self._queues[guild_id] = []
        self._queues[guild_id].append(track)

    def get_next_track(self, guild_id: int) -> Optional[Dict[str, Any]]:
        """Returns the next track and removes it from the queue."""
        if guild_id in self._queues and self._queues[guild_id]:
            return self._queues[guild_id].pop(0)
        return None

    def clear(self, guild_id: int) -> None:
        if guild_id in self._queues:
            self._queues[guild_id].clear()

    def shuffle(self, guild_id: int) -> None:
        if guild_id in self._queues:
            random.shuffle(self._queues[guild_id])

    # --- History Management ---
    
    def add_to_history(self, guild_id: int, track: Dict[str, Any]) -> None:
        if guild_id not in self._history:
            self._history[guild_id] = []
        self._history[guild_id].append(track)
        # Keep history size manageable (optional)
        if len(self._history[guild_id]) > 50:
            self._history[guild_id].pop(0)

    def get_last_track(self, guild_id: int) -> Optional[Dict[str, Any]]:
        """Returns the last played track and removes it from history."""
        if guild_id in self._history and self._history[guild_id]:
            return self._history[guild_id].pop()
        return None
    
    def push_front(self, guild_id: int, track: Dict[str, Any]) -> None:
        """Adds a track to the front of the queue (priority)."""
        if guild_id not in self._queues:
            self._queues[guild_id] = []
        self._queues[guild_id].insert(0, track)
