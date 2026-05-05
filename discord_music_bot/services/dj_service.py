from __future__ import annotations

from datetime import datetime
from typing import Dict, Any, List
import random


class DJService:
    """Template-based DJ comments (MVP, no external LLM)."""

    def __init__(self):
        self._personas = {
            "chill": {
                "intro": [
                    "Спокійний вайб. Далі у нас {title}.",
                    "М'яко входимо в наступний трек: {title}.",
                    "Тримай комфортний настрій, зараз {title}.",
                ],
                "queue_hint": [
                    "У черзі ще {queue_size} трек(ів), не перемикайся.",
                    "Попереду ще {queue_size} трек(ів), буде атмосферно.",
                ],
            },
            "energetic": {
                "intro": [
                    "Піднімаємо градус! Наступний: {title}!",
                    "Гучніше! Влітає {title}!",
                    "Тримаємо темп, зараз буде {title}!",
                ],
                "queue_hint": [
                    "У черзі ще {queue_size} трек(ів) — розганяємось!",
                    "Ще {queue_size} трек(ів) попереду, поїхали!",
                ],
            },
            "funny": {
                "intro": [
                    "Діджей каже: якщо не танцюєш, то хоча б підтакуй. {title}!",
                    "Наступний трек офіційно схвалений вайб-комісією: {title}.",
                    "Увага! Зараз прозвучить {title}, і це не випадково.",
                ],
                "queue_hint": [
                    "Ще {queue_size} трек(ів) у запасі. Музичний серіал триває.",
                    "У черзі {queue_size} трек(ів). Спойлер: буде цікаво.",
                ],
            },
        }

    def generate_comment(self, persona: str, *, context: Dict[str, Any]) -> str:
        style = self._personas.get(persona) or self._personas["chill"]
        title = context.get("title", "Unknown")
        queue_size = int(context.get("queue_size", 0))
        skips = int(context.get("recent_skips", 0))
        hour = int(context.get("hour", datetime.now().hour))

        parts: List[str] = [random.choice(style["intro"]).format(title=title)]

        # Time-aware one-liners
        if hour >= 23 or hour < 6:
            parts.append("Нічний режим активовано.")
        elif hour < 12:
            parts.append("Ранковий заряд прийнято.")

        # Queue-aware and feedback-aware hints
        if queue_size > 0:
            parts.append(random.choice(style["queue_hint"]).format(queue_size=queue_size))
        if skips >= 2:
            parts.append("Бачу скіпи, підкручую підбір під ваш смак.")

        return " ".join(parts)
