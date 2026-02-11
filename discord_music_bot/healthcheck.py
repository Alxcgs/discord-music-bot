"""
Healthcheck та моніторинг зомбі-процесів.
Періодично перевіряє та вбиває orphaned yt-dlp/ffmpeg процеси.
"""

import asyncio
import subprocess
import logging
import os
import signal

logger = logging.getLogger('MusicBot.Healthcheck')


async def cleanup_zombie_processes(interval_seconds: int = 300):
    """
    Фоновий таск: кожні N секунд перевіряє наявність зомбі-процесів
    yt-dlp та ffmpeg і вбиває їх якщо вони зависли.
    """
    while True:
        try:
            await asyncio.sleep(interval_seconds)
            killed = _kill_zombie_processes()
            if killed > 0:
                logger.warning(f"Zombie cleanup: вбито {killed} зомбі-процес(ів).")
        except asyncio.CancelledError:
            logger.info("Zombie cleanup task cancelled.")
            break
        except Exception as e:
            logger.error(f"Zombie cleanup error: {e}")


def _kill_zombie_processes() -> int:
    """Знаходить та вбиває orphaned yt-dlp/ffmpeg процеси. Повертає кількість вбитих."""
    killed = 0

    if os.name == 'nt':
        # Windows
        try:
            result = subprocess.run(
                ['tasklist', '/FO', 'CSV', '/NH'],
                capture_output=True, text=True, timeout=10
            )
            for line in result.stdout.strip().split('\n'):
                if not line:
                    continue
                parts = line.replace('"', '').split(',')
                if len(parts) >= 2:
                    proc_name = parts[0].lower()
                    pid = parts[1]
                    if proc_name in ('yt-dlp.exe', 'ffmpeg.exe'):
                        try:
                            pid_int = int(pid)
                            # Не вбивати себе
                            if pid_int != os.getpid():
                                subprocess.run(
                                    ['taskkill', '/F', '/PID', str(pid_int)],
                                    capture_output=True, timeout=5
                                )
                                killed += 1
                        except (ValueError, subprocess.SubprocessError):
                            pass
        except Exception as e:
            logger.debug(f"Windows zombie check failed: {e}")
    else:
        # Linux/macOS
        try:
            result = subprocess.run(
                ['ps', '-eo', 'pid,ppid,stat,comm', '--no-headers'],
                capture_output=True, text=True, timeout=10
            )
            for line in result.stdout.strip().split('\n'):
                if not line:
                    continue
                parts = line.split()
                if len(parts) >= 4:
                    pid_str, ppid, stat, comm = parts[0], parts[1], parts[2], parts[3]
                    # Zombie або orphaned (ppid=1) процеси yt-dlp/ffmpeg
                    if comm in ('yt-dlp', 'ffmpeg') and ('Z' in stat or ppid == '1'):
                        try:
                            os.kill(int(pid_str), signal.SIGKILL)
                            killed += 1
                        except (ValueError, ProcessLookupError, PermissionError):
                            pass
        except Exception as e:
            logger.debug(f"Linux zombie check failed: {e}")

    return killed


def start_zombie_cleanup(bot_loop: asyncio.AbstractEventLoop, interval: int = 300):
    """Запускає фоновий таск для очищення зомбі-процесів."""
    task = bot_loop.create_task(cleanup_zombie_processes(interval))
    logger.info(f"Zombie cleanup task запущено (інтервал: {interval}с)")
    return task
