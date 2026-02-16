def format_duration(duration_seconds):
    """Форматує тривалість у читабельний формат (HH:MM:SS або MM:SS)."""
    if duration_seconds is None or duration_seconds == 0:
        return "∞"
    
    try:
        duration = int(float(duration_seconds))
        if duration <= 0:
            return "∞"
        hours = duration // 3600
        minutes = (duration % 3600) // 60
        seconds = duration % 60
        
        if hours > 0:
            return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        else:
            return f"{minutes:02d}:{seconds:02d}"
    except (ValueError, TypeError):
        return "∞"