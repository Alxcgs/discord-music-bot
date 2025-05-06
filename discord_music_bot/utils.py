def format_duration(duration_seconds):
    """Форматує тривалість з секунд у формат ГГ:ХХ:СС або ХХ:СС."""
    if duration_seconds is None:
        return "Невідомо"
    minutes, seconds = divmod(duration_seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    else:
        return f"{minutes:02d}:{seconds:02d}"