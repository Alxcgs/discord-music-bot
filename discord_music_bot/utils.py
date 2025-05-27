def format_duration(duration_seconds):
    """Форматує тривалість у читабельний формат."""
    if not duration_seconds:
        return "∞"
    
    try:
        duration = int(float(duration_seconds))
        minutes = duration // 60
        seconds = duration % 60
        return f"{minutes:02d}:{seconds:02d}"
    except (ValueError, TypeError):
        return "∞"