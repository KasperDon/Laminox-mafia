from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardMarkup

from roles import RoleType, ROLES
from database import Player


def join_keyboard(chat_id: int, player_count: int = 0) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text=f"✋ Qo'shilish ({player_count} ta)",
        callback_data=f"join:{chat_id}"
    )
    builder.button(
        text="🚀 O'yinni boshlash",
        callback_data=f"startgame:{chat_id}"
    )
    builder.button(
        text="❌ Bekor qilish",
        callback_data=f"cancelgame:{chat_id}"
    )
    builder.adjust(1)
    return builder.as_markup()


def vote_keyboard(chat_id: int, alive_players: list[Player],
                  voter_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for p in alive_players:
        if p.user_id == voter_id:
            continue
        builder.button(
            text=f"🗳 {p.full_name[:25]}",
            callback_data=f"vote:{chat_id}:{p.user_id}"
        )
    builder.button(text="⏭ O'tkazib yuborish", callback_data=f"skip_vote:{chat_id}")
    builder.adjust(2)
    return builder.as_markup()


def night_action_keyboard(chat_id: int, alive_players: list[Player],
                           actor_id: int, action_type: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for p in alive_players:
        if p.user_id == actor_id:
            continue
        builder.button(
            text=f"🎯 {p.full_name[:25]}",
            callback_data=f"night:{chat_id}:{p.user_id}:{action_type}"
        )
    builder.adjust(2)
    return builder.as_markup()
