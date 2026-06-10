# ---- Build stage ----
FROM python:3.12-slim AS builder

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ---- Runtime stage ----
FROM python:3.12-slim

# Системні залежності: аудіо + Deno (JS runtime для YouTube у yt-dlp)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libopus0 \
    curl \
    unzip \
    ca-certificates \
    && curl -fsSL https://deno.land/install.sh | DENO_INSTALL=/usr/local/deno sh \
    && ln -sf /usr/local/deno/bin/deno /usr/local/bin/deno \
    && rm -rf /var/lib/apt/lists/*

# yt-dlp з EJS-скриптами для YouTube (див. https://github.com/yt-dlp/yt-dlp/wiki/EJS)
RUN pip install --no-cache-dir --upgrade "yt-dlp[default]"

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
    CMD python -c "import os, signal; f='/app/data/bot.pid'; os.path.exists(f) or exit(1); pid=int(open(f).read().strip()); os.kill(pid, 0)" || exit 1

CMD ["python", "main.py"]
