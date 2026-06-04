"""
Asinxron taymer xizmati.
asyncio.Task orqali ishlaydi va DB'da phase_ends_at saqlanadi,
shuning uchun restart bo'lsa ham qolgan vaqt saqlanadi.
"""
import asyncio
import logging
from datetime import datetime, timezone
from typing import Callable, Awaitable

logger = logging.getLogger(__name__)

# chat_id -> faol task
_tasks: dict[int, asyncio.Task] = {}


def schedule(chat_id: int, delay_seconds: int,
             callback: Callable[[], Awaitable[None]]) -> None:
    """
    delay_seconds soniyadan keyin callback'ni ishga tushiradi.
    Agar shu chat_id uchun oldingi task bo'lsa, bekor qilinadi.
    """
    cancel(chat_id)

    async def _runner():
        try:
            await asyncio.sleep(delay_seconds)
            await callback()
        except asyncio.CancelledError:
            logger.debug("Timer cancelled for chat %d", chat_id)
        except Exception as e:
            logger.exception("Timer callback error for chat %d: %s", chat_id, e)

    task = asyncio.create_task(_runner(), name=f"timer_{chat_id}")
    _tasks[chat_id] = task
    logger.debug("Scheduled timer for chat %d in %ds", chat_id, delay_seconds)


def schedule_from_deadline(chat_id: int, deadline_iso: str,
                            callback: Callable[[], Awaitable[None]]) -> None:
    """
    ISO format deadline'dan qolgan vaqtni hisoblab timer o'rnatadi.
    Restart uchun ishlatiladi.
    """
    try:
        deadline = datetime.fromisoformat(deadline_iso)
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        remaining = max(0.0, (deadline - now).total_seconds())
        schedule(chat_id, int(remaining), callback)
    except ValueError as e:
        logger.error("Invalid deadline '%s': %s", deadline_iso, e)


def cancel(chat_id: int) -> None:
    """Shu chat_id uchun faol timerni bekor qiladi."""
    task = _tasks.pop(chat_id, None)
    if task and not task.done():
        task.cancel()


def cancel_all() -> None:
    """Barcha timerlarni bekor qiladi."""
    for chat_id in list(_tasks.keys()):
        cancel(chat_id)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def deadline_iso(seconds: int) -> str:
    """Hozirdan seconds soniya keyin bo'ladigan vaqtni ISO formatda qaytaradi."""
    from datetime import timedelta
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()
