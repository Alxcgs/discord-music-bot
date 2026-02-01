"""
QueueService - сервіс управління чергою треків.
Реалізує логіку черги на базі списку з методами shuffle та move.
"""
import random
from typing import Any, Iterator, List, Optional


class QueueService:
    """
    Черга треків з підтримкою shuffle, move та стандартних операцій.
    Індексація: 0 = наступний трек для відтворення.
    """
    
    def __init__(self, items: Optional[List[Any]] = None):
        self._items: List[Any] = list(items) if items else []
    
    # --- Операції з елементами ---
    
    def add(self, item: Any) -> None:
        """Додає трек в кінець черги."""
        self._items.append(item)
    
    def add_first(self, item: Any) -> None:
        """Додає трек на початок черги (буде відтворено наступним)."""
        self._items.insert(0, item)
    
    def add_many(self, items: List[Any]) -> None:
        """Додає список треків в кінець черги."""
        self._items.extend(items)
    
    def insert(self, index: int, item: Any) -> None:
        """Вставляє трек на позицію index."""
        self._items.insert(index, item)
    
    def pop_first(self) -> Optional[Any]:
        """Видаляє та повертає перший елемент черги."""
        if not self._items:
            return None
        return self._items.pop(0)
    
    def remove(self, index: int) -> Any:
        """Видаляє елемент за індексом та повертає його."""
        return self._items.pop(index)
    
    def clear(self) -> None:
        """Очищає чергу."""
        self._items.clear()
    
    # --- Shuffle & Move ---
    
    def shuffle(self) -> None:
        """Перемішує чергу випадковим чином."""
        if len(self._items) > 1:
            random.shuffle(self._items)
    
    def move(self, from_index: int, to_index: int) -> bool:
        """
        Переміщує елемент з позиції from_index на позицію to_index.
        Індекси нумеруються з 0.
        Повертає True при успіху, False при невалідних індексах.
        """
        n = len(self._items)
        if not (0 <= from_index < n and 0 <= to_index < n):
            return False
        if from_index == to_index:
            return True
        item = self._items.pop(from_index)
        self._items.insert(to_index, item)
        return True
    
    # --- Доступ до даних ---
    
    def __len__(self) -> int:
        return len(self._items)
    
    def __bool__(self) -> bool:
        return len(self._items) > 0
    
    def __getitem__(self, index: int | slice) -> Any:
        return self._items[index]
    
    def __iter__(self) -> Iterator[Any]:
        return iter(self._items)
    
    def copy(self) -> List[Any]:
        """Повертає копію внутрішнього списку (для ітерації/відображення)."""
        return self._items.copy()
