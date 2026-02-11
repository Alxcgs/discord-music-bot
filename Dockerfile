# ---- Build stage ----
FROM python:3.12-slim AS builder

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ---- Runtime stage ----
FROM python:3.12-slim

# Системні залежності для аудіо
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libopus0 \
    && rm -rf /var/lib/apt/lists/*

# Встановити yt-dlp окремо (щоб мати свіжу версію)
RUN pip install --no-cache-dir yt-dlp

# Копіюємо Python-пакети зі stage builder
COPY --from=builder /install /usr/local

# Створюємо non-root користувача
RUN useradd --create-home --shell /bin/bash botuser

WORKDIR /app

# Створюємо директорії для даних та логів
RUN mkdir -p /app/data /app/logs && chown -R botuser:botuser /app

# Копіюємо код
COPY --chown=botuser:botuser . .

# Змінна середовища для шляху до БД
ENV DB_DATA_DIR=/app/data
ENV PYTHONUNBUFFERED=1

USER botuser

# Healthcheck — перевіряємо що процес бота живий
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c "import os, signal; pid = int(open('/app/data/bot.pid').read().strip()); os.kill(pid, 0)" || exit 1

CMD ["python", "main.py"]
