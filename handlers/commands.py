"""
Guruh va shaxsiy buyruqlar handleri.
"""
import logging
from aiogram import Router, Bot, F
from aiogram.filters import Command, CommandStart
from aiogram.types import Message
from aiogram.enums import ChatType
from aiogram.utils.keyboard import InlineKeyboardBuilder

import database as db
from config import settings
from roles import GameState
from game_engine import format_player_list, MIN_PLAYERS
from services.permissions import check_bot_is_admin

logger = logging.getLogger(__name__)
router = Router()

GROUP_FILTER = F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP})

# Sozlash holati (vaqt wizard uchun): chat_id -> {day, vote, night}
_setup: dict[int, dict] = {}


# ─── /start ───────────────────────────────────────────────────────────────────

@router.message(CommandStart())
async def cmd_start(message: Message):
    if message.chat.type == ChatType.PRIVATE:
        await message.answer(
            "👋 Salom! Men <b>Mafia O'yini Boshlovchisi</b>man.\n\n"
            "🎮 <b>Qanday ishlaydi?</b>\n"
            "1. Meni guruhingizga qo'shing va admin qiling\n"
            "2. Guruhda /newgame buyrug'ini bering\n"
            "3. Vaqtlarni sozlang, o'yinchilar qo'shilsin\n"
            "4. O'yinni boshlang — rollar maxfiy tarqatiladi\n"
            "5. O'yin boshlandi! 🎉\n\n"
            "📌 Tunda rol vazifasini bajarish uchun menga shaxsiy xabar "
            "yuboring — siz allaqachon buni qildingiz ✅",
            parse_mode="HTML"
        )
    else:
        await message.answer("🎮 Yangi o'yin uchun: /newgame")


@router.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "📖 <b>Buyruqlar</b>\n\n"
        "/newgame — Yangi o'yin (admin)\n"
        "/cancelgame — O'yinni bekor qilish (admin)\n"
        "/status — O'yin holati\n"
        "/settings — Vaqt sozlamalari (admin)",
        parse_mode="HTML"
    )


# ─── /newgame ─────────────────────────────────────────────────────────────────

@router.message(Command("newgame"), GROUP_FILTER)
async def cmd_newgame(message: Message, bot: Bot):
    chat_id = message.chat.id
    user = message.from_user

    if not await _is_admin(bot, chat_id, user.id):
        await message.answer("❌ Bu buyruq faqat guruh adminlari uchun.")
        return

    if not await check_bot_is_admin(bot, chat_id):
        await message.answer(
            "⚠️ <b>Bot admin emas!</b>\n\n"
            "Botga quyidagi huquqlarni bering:\n"
            "• A'zolarni cheklash (Restrict members)\n"
            "• Xabarlarni o'chirish\n\n"
            "Keyin qaytadan /newgame bering.",
            parse_mode="HTML"
        )
        return

    # Faol o'yinni tekshirish — faqat admin bekor qila oladi
    existing = await db.get_game(chat_id)
    if existing and existing.state not in (GameState.IDLE, GameState.GAME_OVER):
        await message.answer(
            "⚠️ Bu guruhda hozir o'yin bor.\n"
            "Bekor qilish uchun /cancelgame"
        )
        return

    # Vaqt sozlash wizard boshlash
    _setup[chat_id] = {}
    await message.answer(
        "🎮 <b>Yangi o'yin sozlamalari</b>\n\n"
        "☀️ <b>1-qadam: Kunduz muhokama vaqti</b>\n"
        "O'yinchilar gaplashadigan vaqt:",
        reply_markup=_time_keyboard(chat_id, "day",
            [("1 daqiqa", 60), ("2 daqiqa", 120), ("3 daqiqa", 180),
             ("5 daqiqa", 300), ("7 daqiqa", 420), ("10 daqiqa", 600)]),
        parse_mode="HTML"
    )


# ─── /cancelgame ──────────────────────────────────────────────────────────────

@router.message(Command("cancelgame"), GROUP_FILTER)
async def cmd_cancelgame(message: Message, bot: Bot):
    chat_id = message.chat.id
    if not await _is_admin(bot, chat_id, message.from_user.id):
        await message.answer("❌ Bu buyruq faqat guruh adminlari uchun.")
        return

    game = await db.get_game(chat_id)
    if not game or game.state in (GameState.IDLE, GameState.GAME_OVER):
        await message.answer("❌ Bekor qilinadigan faol o'yin yo'q.")
        return

    from services.scheduler import cancel
    from services.permissions import unlock_chat

    cancel(chat_id)
    _setup.pop(chat_id, None)
    await db.update_game_state(chat_id, GameState.GAME_OVER)
    await unlock_chat(bot, chat_id)
    await message.answer("🛑 O'yin bekor qilindi. Yangi o'yin: /newgame")


# ─── /status ──────────────────────────────────────────────────────────────────

@router.message(Command("status"), GROUP_FILTER)
async def cmd_status(message: Message):
    chat_id = message.chat.id
    game = await db.get_game(chat_id)
    if not game or game.state in (GameState.IDLE, GameState.GAME_OVER):
        await message.answer("ℹ️ Faol o'yin yo'q. /newgame")
        return

    players = await db.get_players(chat_id)
    alive = [p for p in players if p.is_alive]
    state_names = {
        GameState.WAITING: "⏳ O'yinchilar kutilmoqda",
        GameState.ROLE_CONFIRMATION: "🎭 Rollar tasdiqlanmoqda",
        GameState.DISTRIBUTING: "📨 Rollar tarqatilmoqda",
        GameState.DAY_DISCUSSION: "☀️ Kunduzgi muhokama",
        GameState.DAY_VOTING: "🗳 Ovoz berish",
        GameState.NIGHT: "🌙 Tun",
    }
    await message.answer(
        f"📊 <b>O'yin holati</b>\n\n"
        f"🔄 {state_names.get(game.state, game.state)}\n"
        f"🔢 Raund: {game.round_number}\n"
        f"👥 Tirik: {len(alive)} / {len(players)}\n\n"
        f"{format_player_list(alive)}",
        parse_mode="HTML"
    )


# ─── /settings ────────────────────────────────────────────────────────────────

@router.message(Command("settings"), GROUP_FILTER)
async def cmd_settings(message: Message, bot: Bot):
    chat_id = message.chat.id
    if not await _is_admin(bot, chat_id, message.from_user.id):
        await message.answer("❌ Bu buyruq faqat guruh adminlari uchun.")
        return

    game = await db.get_game(chat_id)
    if not game or game.state in (GameState.IDLE, GameState.GAME_OVER):
        await message.answer("ℹ️ Faol o'yin yo'q. Sozlamalar /newgame da beriladi.")
        return

    await message.answer(
        f"⚙️ <b>Joriy sozlamalar</b>\n\n"
        f"☀️ Kunduz: <b>{game.day_time}s</b>\n"
        f"🗳 Ovoz berish: <b>{game.vote_time}s</b>\n"
        f"🌙 Tun: <b>{game.night_time}s</b>\n\n"
        f"O'yin davomida /set_day_time, /set_vote_time, /set_night_time bilan o'zgartirish mumkin.",
        parse_mode="HTML"
    )


@router.message(Command("set_day_time"), GROUP_FILTER)
async def cmd_set_day_time(message: Message, bot: Bot):
    await _handle_set_time(message, bot, "day")

@router.message(Command("set_vote_time"), GROUP_FILTER)
async def cmd_set_vote_time(message: Message, bot: Bot):
    await _handle_set_time(message, bot, "vote")

@router.message(Command("set_night_time"), GROUP_FILTER)
async def cmd_set_night_time(message: Message, bot: Bot):
    await _handle_set_time(message, bot, "night")


async def _handle_set_time(message: Message, bot: Bot, time_type: str):
    chat_id = message.chat.id
    if not await _is_admin(bot, chat_id, message.from_user.id):
        await message.answer("❌ Faqat adminlar.")
        return
    limits = {"day": (30, 3600), "vote": (30, 600), "night": (30, 300)}
    names = {"day": "Kunduz", "vote": "Ovoz berish", "night": "Tun"}
    parts = message.text.split()
    if len(parts) < 2:
        mn, mx = limits[time_type]
        await message.answer(f"❓ Foydalanish: {parts[0]} <soniya> ({mn}–{mx})")
        return
    try:
        value = int(parts[1])
        mn, mx = limits[time_type]
        if not (mn <= value <= mx):
            raise ValueError
    except ValueError:
        mn, mx = limits[time_type]
        await message.answer(f"❌ {mn}–{mx} oralig'ida kiriting.")
        return
    await db.update_game_settings(chat_id, **{f"{time_type}_time": value})
    await message.answer(f"✅ {names[time_type]} vaqti: {value}s")


# ─── Wizard keyboard ──────────────────────────────────────────────────────────

def _time_keyboard(chat_id: int, step: str, options: list[tuple[str, int]]):
    builder = InlineKeyboardBuilder()
    for label, value in options:
        builder.button(text=label, callback_data=f"wizard:{chat_id}:{step}:{value}")
    builder.adjust(3)
    return builder.as_markup()


def get_setup(chat_id: int) -> dict:
    return _setup.get(chat_id, {})

def clear_setup(chat_id: int):
    _setup.pop(chat_id, None)


# ─── Yordamchi ────────────────────────────────────────────────────────────────

async def _is_admin(bot: Bot, chat_id: int, user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        return member.status in ("administrator", "creator")
    except Exception:
        return False
