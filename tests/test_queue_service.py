"""
Unit tests for QueueService.
Тестування в ізоляції — MusicRepository замокано.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from discord_music_bot.services.queue_service import QueueService
from discord_music_bot import consts


# ── Fixtures ──────────────────────────────────────────────────────

@pytest.fixture
def mock_repo():
    """Мок MusicRepository — всі async-методи."""
    repo = MagicMock()
    repo.save_queue = AsyncMock()
    repo.clear_queue = AsyncMock()
    repo.add_history_track = AsyncMock()
    repo.pop_last_history_track = AsyncMock()
    repo.load_queue = AsyncMock(return_value=[])
    repo.get_history = AsyncMock(return_value=[])
    return repo


@pytest.fixture
def qs(mock_repo):
    """QueueService з замоканим репозиторієм."""
    return QueueService(mock_repo)


def _track(title="Track", url="https://example.com", duration=180):
    """Helper для створення тестового треку."""
    return {"title": title, "url": url, "webpage_url": url, "duration": duration}


# ── Queue Operations ─────────────────────────────────────────────

class TestAddTrack:
    def test_add_track(self, qs):
        """Трек додається в чергу."""
        track = _track("Song A")
        qs.add_track(1, track)
        assert len(qs.get_queue(1)) == 1
        assert qs.get_queue(1)[0]["title"] == "Song A"

    def test_add_tracks(self, qs):
        """Список треків додається одразу."""
        tracks = [_track(f"Song {i}") for i in range(5)]
        qs.add_tracks(1, tracks)
        assert len(qs.get_queue(1)) == 5

    def test_add_creates_queue_for_new_guild(self, qs):
        """Черга створюється автоматично для нового guild_id."""
        assert qs.get_queue(999) == []
        qs.add_track(999, _track())
        assert len(qs.get_queue(999)) == 1


class TestGetNextTrack:
    def test_get_next_track_fifo(self, qs):
        """Треки повертаються у FIFO порядку."""
        qs.add_track(1, _track("First"))
        qs.add_track(1, _track("Second"))
        result = qs.get_next_track(1)
        assert result["title"] == "First"
        assert len(qs.get_queue(1)) == 1

    def test_get_next_track_empty(self, qs):
        """Порожня черга повертає None."""
        assert qs.get_next_track(1) is None

    def test_get_next_track_removes_from_queue(self, qs):
        """get_next_track видаляє трек з черги."""
        qs.add_track(1, _track("Only"))
        qs.get_next_track(1)
        assert len(qs.get_queue(1)) == 0


class TestClear:
    def test_clear(self, qs):
        """Черга очищається повністю."""
        qs.add_tracks(1, [_track(f"S{i}") for i in range(3)])
        qs.clear(1)
        assert len(qs.get_queue(1)) == 0

    def test_clear_nonexistent_guild(self, qs):
        """Очистка неіснуючої черги не викликає помилку."""
        qs.clear(999)  # Не повинно кидати exception


class TestShuffle:
    def test_shuffle_changes_order(self, qs):
        """Shuffle змінює порядок (з високою ймовірністю)."""
        tracks = [_track(f"Song {i}") for i in range(20)]
        qs.add_tracks(1, tracks)
        original_order = [t["title"] for t in qs.get_queue(1)]
        qs.shuffle(1)
        shuffled_order = [t["title"] for t in qs.get_queue(1)]
        # З 20 елементами ймовірність того ж порядку ~= 1/20! ≈ 0
        assert shuffled_order != original_order

    def test_shuffle_preserves_count(self, qs):
        """Shuffle зберігає кількість треків."""
        qs.add_tracks(1, [_track(f"S{i}") for i in range(5)])
        qs.shuffle(1)
        assert len(qs.get_queue(1)) == 5


class TestPushFront:
    def test_push_front(self, qs):
        """push_front додає трек на початок черги."""
        qs.add_track(1, _track("Original"))
        qs.push_front(1, _track("Priority"))
        assert qs.get_queue(1)[0]["title"] == "Priority"
        assert len(qs.get_queue(1)) == 2


class TestMoveTrack:
    def test_move_track_forward(self, qs):
        """Трек можна перемістити вперед (на меншу позицію)."""
        qs.add_tracks(1, [_track(f"S{i}") for i in range(5)])
        result = qs.move_track(1, 5, 1)  # S4 → позиція 1
        assert result is not None
        assert result["title"] == "S4"
        assert qs.get_queue(1)[0]["title"] == "S4"

    def test_move_track_backward(self, qs):
        """Трек можна перемістити назад (на більшу позицію)."""
        qs.add_tracks(1, [_track(f"S{i}") for i in range(5)])
        result = qs.move_track(1, 1, 5)  # S0 → позиція 5
        assert result is not None
        assert qs.get_queue(1)[-1]["title"] == "S0"

    def test_move_track_invalid_position(self, qs):
        """Некоректні позиції повертають None."""
        qs.add_tracks(1, [_track(f"S{i}") for i in range(3)])
        assert qs.move_track(1, 0, 1) is None   # 0 — невалідна
        assert qs.move_track(1, 1, 10) is None   # 10 — за межами

    def test_move_track_same_position(self, qs):
        """Переміщення на ту ж позицію повертає трек без зміни."""
        qs.add_tracks(1, [_track(f"S{i}") for i in range(3)])
        result = qs.move_track(1, 2, 2)
        assert result is not None
        assert result["title"] == "S1"

    def test_move_track_empty_queue(self, qs):
        """Переміщення в порожній черзі повертає None."""
        assert qs.move_track(1, 1, 2) is None


class TestPeekNext:
    def test_peek_next(self, qs):
        """peek_next повертає трек без видалення."""
        qs.add_track(1, _track("Peek Me"))
        result = qs.peek_next(1)
        assert result["title"] == "Peek Me"
        assert len(qs.get_queue(1)) == 1  # Не видалений!

    def test_peek_next_empty(self, qs):
        """peek_next з порожньої черги повертає None."""
        assert qs.peek_next(1) is None


# ── History ───────────────────────────────────────────────────────

class TestHistory:
    def test_add_to_history(self, qs):
        """Трек додається в історію."""
        qs.add_to_history(1, _track("Hist Track"))
        assert len(qs._history.get(1, [])) == 1

    def test_history_max_size(self, qs):
        """Історія обмежена MAX_HISTORY_SIZE."""
        for i in range(consts.MAX_HISTORY_SIZE + 20):
            qs.add_to_history(1, _track(f"H{i}"))
        assert len(qs._history[1]) == consts.MAX_HISTORY_SIZE

    def test_get_last_track(self, qs):
        """get_last_track повертає останній доданий та видаляє його."""
        qs.add_to_history(1, _track("First"))
        qs.add_to_history(1, _track("Last"))
        result = qs.get_last_track(1)
        assert result["title"] == "Last"
        assert len(qs._history[1]) == 1

    def test_get_last_track_empty(self, qs):
        """get_last_track з порожньої історії повертає None."""
        assert qs.get_last_track(1) is None


# ── Isolation ─────────────────────────────────────────────────────

class TestGuildIsolation:
    def test_separate_queues(self, qs):
        """Різні guild_id мають ізольовані черги."""
        qs.add_track(1, _track("Guild 1"))
        qs.add_track(2, _track("Guild 2"))
        assert len(qs.get_queue(1)) == 1
        assert len(qs.get_queue(2)) == 1
        assert qs.get_queue(1)[0]["title"] == "Guild 1"
        assert qs.get_queue(2)[0]["title"] == "Guild 2"

    def test_clear_one_guild(self, qs):
        """Очистка однієї черги не впливає на іншу."""
        qs.add_track(1, _track("Keep"))
        qs.add_track(2, _track("Clear"))
        qs.clear(2)
        assert len(qs.get_queue(1)) == 1
        assert len(qs.get_queue(2)) == 0
