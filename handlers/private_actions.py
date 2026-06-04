"""
Shaxsiy xabardagi tun harakatlari handleri.
"""
import logging
from aiogram import Router, Bot, F
from aiogram.types import CallbackQuery
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

import database as db
from roles import GameState, RoleType, ROLES
from game_engine import needs_night_action
from keyboards import night_action_keyboard

logger = logging.getLogger(__name__)
router = Router()


@router.callback_query(F.data.startswith("night:"))
async def cb_night_action(call: CallbackQuery, bot: Bot):
    """
    Format: night:{chat_id}:{target_user_id}:{action_type}
    """
    parts = call.data.split(":")
    chat_id = int(parts[1])
    target_id = int(parts[2])
    action_type = parts[3]
    actor_id = call.from_user.id

    game = await db.get_game(chat_id)
    if not game or game.state != GameState.NIGHT:
        await call.answer("❌ Hozir tun bosqichi emas.", show_alert=True)
        return

    actor = await db.get_player(chat_id, actor_id)
    if not actor or not actor.is_alive:
        await call.answer("❌ Siz o'yinda yo'qsiz.", show_alert=True)
        return

    if not actor.role or not needs_night_action(actor.role):
        await call.answer("❌ Sizning rolingiz tunda harakat qilmaydi.", show_alert=True)
        return

    if await db.has_night_action(game.id, game.round_number, actor_id):
        await call.answer("❌ Siz allaqachon harakat qildingiz!", show_alert=True)
        return

    target = await db.get_player(chat_id, target_id)
    if not target or not target.is_alive:
        await call.answer("❌ Bu o'yinchi o'yinda emas.", show_alert=True)
        return

    await db.save_night_action(
        game_id=game.id,
        chat_id=chat_id,
        round_number=game.round_number,
        actor_user_id=actor_id,
        target_user_id=target_id,
        action_type=action_type,
    )

    role = ROLES[actor.role]
    confirmations = {
        "kill":        f"🎯 Tanlov: {target.full_name}",
        "heal":        f"💊 Davolash: {target.full_name}",
        "check":       f"🔍 Tekshirish: {target.full_name}",
        "maniac_kill": f"🔪 Qurbon: {target.full_name}",
    }
    await call.answer(confirmations.get(action_type, "✅ Qabul qilindi!"))

    try:
        await call.message.edit_text(
            f"✅ <b>Harakatingiz qabul qilindi!</b>\n\n"
            f"{role.emoji} <b>{role.name}</b>:\n"
            f"→ {target.full_name}\n\n"
            f"<i>Tong natijalarini kuting...</i>",
            parse_mode="HTML"
        )
    except (TelegramBadRequest, TelegramForbiddenError):
        pass

    # Barcha tunda harakat qiladiganlar harakat qildimi?
    await _check_all_night_actions_done(bot, game, chat_id)


async def _check_all_night_actions_done(bot: Bot, game: db.Game, chat_id: int):
    alive = await db.get_players(chat_id, alive_only=True)
    night_actors = [p for p in alive if p.role and needs_night_action(p.role)]

    if not night_actors:
        return

    for actor in night_actors:
        if not await db.has_night_action(game.id, game.round_number, actor.user_id):
            return

    # Hammasi harakat qildi — muddatdan oldin tugatish
    from services.scheduler import cancel
    cancel(chat_id)

    # Guruhga xabar yuborib, tun yakunini ishga tushirish
    # Import circular bo'lmasligi uchun bu yerda import qilamiz
    from handlers.callbacks import _end_night_phase

    try:
        sent = await bot.send_message(
            chat_id,
            "⚡ Barcha harakatlar tugadi. Tong kelmoqda...",
        )
        await _end_night_phase(sent, bot, chat_id)
    except Exception as e:
        logger.error("Failed to end night early for chat %d: %s", chat_id, e)
