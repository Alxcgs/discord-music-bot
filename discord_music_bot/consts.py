# discord_music_bot/consts.py

# --- Pagination Constants ---
ITEMS_PER_PAGE = 10
SEARCH_ITEMS_PER_PAGE = 5
MAX_QUEUE_FIELD_LENGTH = 1000
MAX_HISTORY_SIZE = 50
MAX_PLAYLIST_SIZE = 100
PREVIEW_QUEUE_SIZE = 5
EMOJI_PLAYLIST = "📋"

# --- Timeouts (Seconds) ---
TIMEOUT_VOICE_DISCONNECT = 60
TIMEOUT_EMPTY_CHANNEL = 10
TIMEOUT_VOICE_CONNECT = 60.0 # Connection timeout (increased for stability)
TIMEOUT_SEARCH_MENU = 60
TIMEOUT_VIEW = 60
TIMEOUT_BUTTON_INTERACTION = None # Persistent view usually, but View(timeout=X) uses this

# --- Colors ---
COLOR_EMBED_NORMAL = 0x9b59b6 # Purple
COLOR_EMBED_PLAYING = 0x3498db # Blue
COLOR_EMBED_ERROR = 0xe74c3c    # Red (unused yet but good to have)

# --- Emojis ---
EMOJI_PREVIOUS = "⏮️"
EMOJI_PAUSE = "⏸️"
EMOJI_RESUME = "▶️"
EMOJI_SKIP = "⏭️"
EMOJI_STOP = "⏹️"
EMOJI_QUEUE = "📄"
EMOJI_LEAVE = "🚪"
EMOJI_NOTE = "🎶"
EMOJI_SEARCH = "🔍"
EMOJI_ERROR = "❌"
EMOJI_SUCCESS = "✅"
EMOJI_WAIT = "⏳"
EMOJI_NEXT_PAGE = "▶️"
EMOJI_PREV_PAGE = "◀️"
EMOJI_FIRST_PAGE = "⏮️"
EMOJI_LAST_PAGE = "⏭️"
EMOJI_REFRESH = "🔄"
EMOJI_CANCEL = "❌"
EMOJI_LEFT_ARROW = "⬅️"
EMOJI_RIGHT_ARROW = "➡️"
EMOJI_VOLUME_DOWN = "🔉"
EMOJI_VOLUME_UP = "🔊"
EMOJI_VOLUME_MUTE = "🔇"
EMOJI_HISTORY = "📜"
EMOJI_STATS = "📊"

# --- Volume ---
DEFAULT_VOLUME = 0.5
VOLUME_STEP = 0.1
VOLUME_MIN = 0.0
VOLUME_MAX = 2.0

# --- YTDL Options ---
YTDL_OPTIONS_LIGHT = {
    'quiet': True,
    'no_warnings': True,
    'extract_flat': True,
    'skip_download': True,
    'format': 'bestaudio[acodec=opus][abr<=128]/bestaudio/best',
    'nocheckcertificate': True,
    'ignoreerrors': True,
    'socket_timeout': 5,
    'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'opus', 'preferredquality': '128'}]
}

# --- Messages ---
MSG_NOT_IN_VOICE = "Ви не в голосовому каналі!"
MSG_BOT_NOT_IN_VOICE = "Бот наразі не в голосовому каналі."
MSG_SAME_VOICE_CHANNEL = "Ви повинні бути в тому ж голосовому каналі, що й бот."
MSG_QUEUE_EMPTY = "Черга порожня"
MSG_NOTHING_PLAYING = "Зараз нічого не грає."
MSG_STOPPED = "⏹️ Зупинено."
MSG_PAUSED = "⏸️ Пауза."
MSG_RESUMED = "▶️ Продовжуємо."
MSG_SKIPPED = "⏭️ Пропущено."
MSG_LEFT = "👋 Бувай!"
