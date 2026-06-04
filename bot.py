"""
Mafia O'yini Boshlovchi Bot — asosiy kirish nuqtasi.
"""
import asyncio
import logging
import sys
from datetime import datetime, timezone

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from config import settings
from database import init_db, get_active_games
from roles import GameState
from services import scheduler
from handlers.commands import router as commands_router
from handlers.callbacks import router as callbacks_router, _start_day_phase, _end_night_phase
from handlers.private_actions import router as private_router

# ─── Logging sozlash ──────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("mafia_bot.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)

# Aiogram ichki loglarini kamaytirish
logging.getLogger("aiogram").setLevel(logging.WARNING)


# ─── Startup: faol o'yinlarni tiklash ────────────────────────────────────────

async def restore_active_games(bot: Bot) -> None:
    """
    Bot restart bo'lgandan keyin faol o'yinlarni tiklaydi.
    phase_ends_at dan qolgan vaqtni hisoblab timer o'rnatadi.
    """
    active_games = await get_active_games()
    if not active_games:
        logger.info("No active games to restore.")
        return

    logger.info("Restoring %d active game(s)...", len(active_games))

    for game in active_games:
        logger.info("Restoring game in chat %d | state: %s", game.chat_id, game.state)

        if game.state == GameState.WAITING:
            # Qo'shilish bosqichida qolgan — davom ettiramiz (timer yo'q)
            continue

        if not game.phase_ends_at:
            # Deadline yo'q — xavfsiz holat uchun keyingi bosqichni boshlash
            logger.warning("Game %d has no deadline, skipping restore.", game.chat_id)
            continue

        try:
            deadline = datetime.fromisoformat(game.phase_ends_at)
            if deadline.tzinfo is None:
                deadline = deadline.replace(tzinfo=timezone.utc)
            now = datetime.now(timezone.utc)
            remaining = max(5.0, (deadline - now).total_seconds())

            chat_id = game.chat_id

            if game.state == GameState.DAY_DISCUSSION:
                sent = await bot.send_message(
                    chat_id,
                    f"🔄 Bot qayta ishga tushdi. Muhokama {int(remaining)} soniyada tugaydi."
                )
                from handlers.callbacks import _end_day_phase
                scheduler.schedule(
                    chat_id, int(remaining),
                    lambda m=sent, b=bot, cid=chat_id: _end_day_phase(m, b, cid)
                )

            elif game.state == GameState.DAY_VOTING:
                sent = await bot.send_message(
                    chat_id,
                    f"🔄 Bot qayta ishga tushdi. Ovoz berish {int(remaining)} soniyada tugaydi."
                )
                from handlers.callbacks import _end_vote_phase
                scheduler.schedule(
                    chat_id, int(remaining),
                    lambda m=sent, b=bot, cid=chat_id: _end_vote_phase(m, b, cid)
                )

            elif game.state == GameState.NIGHT:
                sent = await bot.send_message(
                    chat_id,
                    f"🔄 Bot qayta ishga tushdi. Tun {int(remaining)} soniyada tugaydi."
                )
                scheduler.schedule(
                    chat_id, int(remaining),
                    lambda m=sent, b=bot, cid=chat_id: _end_night_phase(m, b, cid)
                )

        except Exception as e:
            logger.error("Failed to restore game %d: %s", game.chat_id, e)


# ─── Main ─────────────────────────────────────────────────────────────────────

async def main() -> None:
    logger.info("=" * 50)
    logger.info("Mafia Bot ishga tushmoqda...")
    logger.info("=" * 50)

    # Ma'lumotlar bazasini ishga tushirish
    await init_db()

    # Bot va Dispatcher
    bot = Bot(
        token=settings.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()

    # Router'larni ulash (tartib muhim: private > callbacks > commands)
    dp.include_router(private_router)
    dp.include_router(callbacks_router)
    dp.include_router(commands_router)

    # Startup hook
    @dp.startup()
    async def on_startup():
        bot_info = await bot.get_me()
        logger.info("Bot: @%s (id: %d)", bot_info.username, bot_info.id)
        await restore_active_games(bot)

    # Shutdown hook
    @dp.shutdown()
    async def on_shutdown():
        logger.info("Bot to'xtatilmoqda...")
        scheduler.cancel_all()
        await bot.session.close()

    # Polling boshlash
    logger.info("Polling boshlandi. To'xtatish uchun Ctrl+C")
    await dp.start_polling(
        bot,
        allowed_updates=["message", "callback_query", "chat_member"],
        drop_pending_updates=True,
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot foydalanuvchi tomonidan to'xtatildi.")
