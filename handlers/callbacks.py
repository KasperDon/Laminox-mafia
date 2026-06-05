"""
Inline tugmalar callback handleri + o'yin bosqichlari.
"""
import html as html_module
import asyncio
import logging
from aiogram import Router, Bot, F
from aiogram.types import CallbackQuery, Message
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

import database as db
from roles import GameState, RoleType, ROLES
from game_engine import (
    assign_roles, check_win_condition,
    format_player_list, player_mention, MIN_PLAYERS,
    needs_night_action, get_night_action_type,
)
from keyboards import (
    join_keyboard, vote_keyboard, night_action_keyboard,
)
from services.permissions import lock_chat, unlock_chat
from services import scheduler

logger = logging.getLogger(__name__)
router = Router()


# ─── Vaqt sozlash wizard ──────────────────────────────────────────────────────
# Format: wizard:{chat_id}:{step}:{value}

@router.callback_query(F.data.startswith("wizard:"))
async def cb_wizard(call: CallbackQuery, bot: Bot):
    parts = call.data.split(":")
    chat_id = int(parts[1])
    step = parts[2]
    value = int(parts[3])

    from handlers.commands import get_setup, get_setup_creator, clear_setup, _time_keyboard

    # Wizard — wizardni boshlagan odam yoki admin
    setup_creator = get_setup_creator(chat_id)
    if setup_creator != call.from_user.id:
        if not await _is_admin(bot, chat_id, call.from_user.id):
            await call.answer("❌ Faqat o'yin boshlovchisi yoki admin.", show_alert=True)
            return
    setup = get_setup(chat_id)
    setup[step] = value
    await call.answer()

    if step == "day":
        await call.message.edit_text(
            f"🎮 <b>O'yin sozlamalari</b>\n\n"
            f"☀️ Kunduz: <b>{value}s</b> ✅\n\n"
            f"🗳 <b>2-qadam: Ovoz berish vaqti</b>\n"
            f"Kuni bo'yi muhokamadan keyin ovoz beriladi:",
            reply_markup=_time_keyboard(chat_id, "vote",
                [("30 soniya", 30), ("1 daqiqa", 60), ("2 daqiqa", 120),
                 ("3 daqiqa", 180), ("5 daqiqa", 300)]),
            parse_mode="HTML"
        )

    elif step == "vote":
        day = setup.get("day", 300)
        await call.message.edit_text(
            f"🎮 <b>O'yin sozlamalari</b>\n\n"
            f"☀️ Kunduz: <b>{day}s</b> ✅\n"
            f"🗳 Ovoz berish: <b>{value}s</b> ✅\n\n"
            f"🌙 <b>3-qadam: Tun vaqti</b>\n"
            f"Mafiya va boshqa rollar harakat qiladigan vaqt:",
            reply_markup=_time_keyboard(chat_id, "night",
                [("30 soniya", 30), ("45 soniya", 45), ("1 daqiqa", 60),
                 ("2 daqiqa", 120)]),
            parse_mode="HTML"
        )

    elif step == "night":
        day = setup.get("day", 300)
        vote = setup.get("vote", 120)

        # O'yin yaratish
        game = await db.create_game(
            chat_id=chat_id,
            created_by=call.from_user.id,
            day_time=day,
            vote_time=vote,
            night_time=value,
        )
        clear_setup(chat_id)

        await call.message.edit_text(
            f"✅ <b>Sozlamalar tayyor!</b>\n\n"
            f"☀️ Kunduz: <b>{day}s</b>\n"
            f"🗳 Ovoz berish: <b>{vote}s</b>\n"
            f"🌙 Tun: <b>{value}s</b>\n\n"
            f"👇 O'yinchilar qo'shilsin:",
            parse_mode="HTML"
        )
        # Join xabari
        mention = f'<a href="tg://user?id={call.from_user.id}">{html_module.escape(call.from_user.full_name)}</a>'
        await call.message.answer(
            f"🎮 <b>Mafia o'yini boshlanmoqda!</b>\n\n"
            f"👤 Boshlovchi: {mention}\n"
            f"Kamida <b>{MIN_PLAYERS} ta</b> o'yinchi kerak.\n\n"
            f"⬇️ Qo'shilish uchun tugmani bosing:",
            reply_markup=join_keyboard(chat_id, 0),
            parse_mode="HTML"
        )


# ─── Qo'shilish ───────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("join:"))
async def cb_join(call: CallbackQuery, bot: Bot):
    chat_id = int(call.data.split(":")[1])
    user = call.from_user

    game = await db.get_game(chat_id)
    if not game or game.state != GameState.WAITING:
        await call.answer("❌ O'yinga qo'shilish vaqti tugadi.", show_alert=True)
        return

    # Foydalanuvchi botga /start bosganmi tekshirish
    try:
        await bot.send_chat_action(user.id, "typing")
    except (TelegramBadRequest, TelegramForbiddenError):
        await call.answer(
            "⚠️ Avval @Laminox_Mafia_bot ga shaxsiy xabarda /start bosing!\n"
            "Keyin qayta urinib ko'ring.",
            show_alert=True
        )
        return

    added = await db.add_player(
        game_id=game.id, chat_id=chat_id,
        user_id=user.id, username=user.username,
        full_name=user.full_name,
    )
    if not added:
        await call.answer("✅ Siz allaqachon ro'yxatdasiz!", show_alert=False)
        return

    players = await db.get_players(chat_id)
    await call.answer(f"✅ Qo'shildingiz!")

    try:
        await call.message.edit_reply_markup(
            reply_markup=join_keyboard(chat_id, len(players))
        )
    except TelegramBadRequest:
        pass

    names = "\n".join(f"{i}. {player_mention(p)}" for i, p in enumerate(players, 1))
    await call.message.answer(
        f"✋ <b>{html_module.escape(user.full_name)}</b> qo'shildi!\n\n"
        f"👥 O'yinchilar ({len(players)}/{MIN_PLAYERS} minimum):\n{names}",
        parse_mode="HTML"
    )


# Rol taqsimotini saqlash (xotirada)
_custom_dist: dict[int, dict] = {}   # chat_id -> {RoleType: count}


def _make_role_keyboard(chat_id: int, dist: dict) -> "InlineKeyboardMarkup":
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    builder = InlineKeyboardBuilder()

    # Qo'shish mumkin bo'lgan rollar (faqat yo'qlari)
    addable = [r for r in [RoleType.DON, RoleType.MANIAC, RoleType.COMMISSIONER, RoleType.DOCTOR]
               if r not in dist or dist[r] == 0]
    for r in addable:
        role = ROLES[r]
        builder.button(text=f"➕ {role.emoji} {role.name}",
                       callback_data=f"rdist_add:{chat_id}:{r.value}")

    # Olib tashlash mumkin (MAFIA va CIVILIAN dan tashqari, kamida 1 qolsin)
    removable = [r for r in dist if r not in (RoleType.MAFIA, RoleType.CIVILIAN) and dist.get(r, 0) > 0]
    for r in removable:
        role = ROLES[r]
        builder.button(text=f"➖ {role.emoji} {role.name}",
                       callback_data=f"rdist_rm:{chat_id}:{r.value}")

    # Mafiya +/-
    mafia_cnt = dist.get(RoleType.MAFIA, 1)
    builder.button(text=f"🔫 Mafiya: {mafia_cnt}  ➕",
                   callback_data=f"rdist_mafia_add:{chat_id}")
    if mafia_cnt > 1:
        builder.button(text=f"🔫 Mafiya: {mafia_cnt}  ➖",
                       callback_data=f"rdist_mafia_rm:{chat_id}")

    builder.button(text="🔀 Avtomatik taqsimlash", callback_data=f"rdist_auto:{chat_id}")
    builder.button(text="✅ Tasdiqlash va boshlash", callback_data=f"rdist_confirm:{chat_id}")
    builder.adjust(1)
    return builder.as_markup()


def _dist_text(dist: dict, player_count: int) -> str:
    from roles import format_distribution
    lines = format_distribution(dist)
    civilian = dist.get(RoleType.CIVILIAN, 0)
    total = sum(dist.values())
    return (
        f"👥 O'yinchilar: <b>{player_count} ta</b>\n\n"
        f"🎭 <b>Rol taqsimoti:</b>\n{lines}\n\n"
        f"{'✅ Jami ' + str(total) + ' ta — to\'g\'ri' if total == player_count else '⚠️ Jami ' + str(total) + ' / ' + str(player_count) + ' — muvofiqlashtiring'}"
    )


# ─── O'yinni boshlash ─────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("startgame:"))
async def cb_start_game_button(call: CallbackQuery, bot: Bot):
    chat_id = int(call.data.split(":")[1])
    game = await db.get_game(chat_id)
    if not await _is_creator_or_admin(bot, chat_id, call.from_user.id, game):
        await call.answer("❌ Faqat o'yin boshlovchisi yoki admin.", show_alert=True)
        return
    await call.answer()
    await _do_start_game(call.message, bot, chat_id)


async def _do_start_game(message: Message, bot: Bot, chat_id: int):
    game = await db.get_game(chat_id)
    if not game or game.state != GameState.WAITING:
        await message.answer("❌ O'yin kutish bosqichida emas.")
        return

    players = await db.get_players(chat_id)
    if len(players) < MIN_PLAYERS:
        await message.answer(
            f"⚠️ Kamida <b>{MIN_PLAYERS}</b> o'yinchi kerak. Hozir: <b>{len(players)}</b>",
            parse_mode="HTML"
        )
        return

    # Avtomatik taqsimot taklifi
    from roles import get_role_distribution
    dist = dict(get_role_distribution(len(players)))
    _custom_dist[chat_id] = dist

    await message.answer(
        _dist_text(dist, len(players)) +
        "\n\nO'zgartirish yoki tasdiqlang:",
        reply_markup=_make_role_keyboard(chat_id, dist),
        parse_mode="HTML"
    )


# ─── Rol taqsimoti tugmalari ──────────────────────────────────────────────────

@router.callback_query(F.data.startswith("rdist_add:"))
async def cb_rdist_add(call: CallbackQuery, bot: Bot):
    parts = call.data.split(":")
    chat_id, role_val = int(parts[1]), parts[2]
    game = await db.get_game(chat_id)
    if not await _is_creator_or_admin(bot, chat_id, call.from_user.id, game):
        await call.answer("❌ Faqat o'yin boshlovchisi yoki admin.", show_alert=True); return

    role_type = RoleType(role_val)
    dist = _custom_dist.get(chat_id, {})
    players = await db.get_players(chat_id)

    if dist.get(RoleType.CIVILIAN, 0) <= 1:
        await call.answer("❌ Yetarli Tinch aholi qolmadi!", show_alert=True); return

    dist[role_type] = dist.get(role_type, 0) + 1
    dist[RoleType.CIVILIAN] = dist.get(RoleType.CIVILIAN, 0) - 1
    _custom_dist[chat_id] = dist
    await call.answer(f"✅ {ROLES[role_type].name} qo'shildi")
    await _refresh_dist_msg(call, chat_id, dist, len(players))


@router.callback_query(F.data.startswith("rdist_rm:"))
async def cb_rdist_rm(call: CallbackQuery, bot: Bot):
    parts = call.data.split(":")
    chat_id, role_val = int(parts[1]), parts[2]
    game = await db.get_game(chat_id)
    if not await _is_creator_or_admin(bot, chat_id, call.from_user.id, game):
        await call.answer("❌ Faqat o'yin boshlovchisi yoki admin.", show_alert=True); return

    role_type = RoleType(role_val)
    dist = _custom_dist.get(chat_id, {})
    players = await db.get_players(chat_id)

    if dist.get(role_type, 0) <= 0:
        await call.answer("Bu rol allaqachon yo'q.", show_alert=True); return

    dist[RoleType.CIVILIAN] = dist.get(RoleType.CIVILIAN, 0) + dist.pop(role_type)
    _custom_dist[chat_id] = dist
    await call.answer(f"✅ {ROLES[role_type].name} olib tashlandi")
    await _refresh_dist_msg(call, chat_id, dist, len(players))


@router.callback_query(F.data.startswith("rdist_mafia_add:"))
async def cb_rdist_mafia_add(call: CallbackQuery, bot: Bot):
    chat_id = int(call.data.split(":")[1])
    game = await db.get_game(chat_id)
    if not await _is_creator_or_admin(bot, chat_id, call.from_user.id, game):
        await call.answer("❌ Faqat o'yin boshlovchisi yoki admin.", show_alert=True); return

    dist = _custom_dist.get(chat_id, {})
    players = await db.get_players(chat_id)

    if dist.get(RoleType.CIVILIAN, 0) <= 1:
        await call.answer("❌ Yetarli Tinch aholi yo'q!", show_alert=True); return

    dist[RoleType.MAFIA] = dist.get(RoleType.MAFIA, 0) + 1
    dist[RoleType.CIVILIAN] -= 1
    _custom_dist[chat_id] = dist
    await call.answer("✅ Mafiya +1")
    await _refresh_dist_msg(call, chat_id, dist, len(players))


@router.callback_query(F.data.startswith("rdist_mafia_rm:"))
async def cb_rdist_mafia_rm(call: CallbackQuery, bot: Bot):
    chat_id = int(call.data.split(":")[1])
    game = await db.get_game(chat_id)
    if not await _is_creator_or_admin(bot, chat_id, call.from_user.id, game):
        await call.answer("❌ Faqat o'yin boshlovchisi yoki admin.", show_alert=True); return

    dist = _custom_dist.get(chat_id, {})
    players = await db.get_players(chat_id)

    if dist.get(RoleType.MAFIA, 0) <= 1:
        await call.answer("❌ Kamida 1 ta Mafiya bo'lishi shart!", show_alert=True); return

    dist[RoleType.MAFIA] -= 1
    dist[RoleType.CIVILIAN] = dist.get(RoleType.CIVILIAN, 0) + 1
    _custom_dist[chat_id] = dist
    await call.answer("✅ Mafiya -1")
    await _refresh_dist_msg(call, chat_id, dist, len(players))


@router.callback_query(F.data.startswith("rdist_auto:"))
async def cb_rdist_auto(call: CallbackQuery, bot: Bot):
    chat_id = int(call.data.split(":")[1])
    game = await db.get_game(chat_id)
    if not await _is_creator_or_admin(bot, chat_id, call.from_user.id, game):
        await call.answer("❌ Faqat o'yin boshlovchisi yoki admin.", show_alert=True); return

    from roles import get_role_distribution
    players = await db.get_players(chat_id)
    dist = dict(get_role_distribution(len(players)))
    _custom_dist[chat_id] = dist
    await call.answer("🔀 Avtomatik taqsimlandi")
    await _refresh_dist_msg(call, chat_id, dist, len(players))


@router.callback_query(F.data.startswith("rdist_confirm:"))
async def cb_rdist_confirm(call: CallbackQuery, bot: Bot):
    chat_id = int(call.data.split(":")[1])
    game = await db.get_game(chat_id)
    if not await _is_creator_or_admin(bot, chat_id, call.from_user.id, game):
        await call.answer("❌ Faqat o'yin boshlovchisi yoki admin.", show_alert=True); return

    dist = _custom_dist.get(chat_id)
    players = await db.get_players(chat_id)
    total = sum(dist.values()) if dist else 0

    if total != len(players):
        await call.answer(
            f"⚠️ Rollar soni ({total}) o'yinchilar soniga ({len(players)}) mos kelmaydi!",
            show_alert=True
        )
        return

    game = await db.get_game(chat_id)
    if not game:
        await call.answer("❌ O'yin topilmadi.", show_alert=True); return

    await call.answer("✅ Boshlayapmiz!")
    try:
        await call.message.edit_reply_markup(reply_markup=None)
    except TelegramBadRequest:
        pass

    _custom_dist.pop(chat_id, None)
    await _distribute_roles_and_start(call.message, bot, game, custom_dist=dist)


async def _refresh_dist_msg(call: CallbackQuery, chat_id: int,
                              dist: dict, player_count: int) -> None:
    try:
        await call.message.edit_text(
            _dist_text(dist, player_count) + "\n\nO'zgartirish yoki tasdiqlang:",
            reply_markup=_make_role_keyboard(chat_id, dist),
            parse_mode="HTML"
        )
    except TelegramBadRequest:
        pass


# ─── Rollarni tarqatish ───────────────────────────────────────────────────────

async def _distribute_roles_and_start(message: Message, bot: Bot, game: db.Game,
                                       custom_dist: dict | None = None):
    chat_id = game.chat_id
    await db.update_game_state(chat_id, GameState.DISTRIBUTING)

    # Rollarni tayinlash — assignment: {user_id: RoleType}
    assignment = await assign_roles(game, custom_dist=custom_dist)
    if not assignment:
        await message.answer("❌ Rol tayinlashda xato. /cancelgame va qayta urinib ko'ring.")
        return

    players = await db.get_players(chat_id)

    # Mafiya a'zolari (assignment dan)
    mafia_uids = [uid for uid, r in assignment.items() if r in (RoleType.MAFIA, RoleType.DON)]
    mafia_players = [p for p in players if p.user_id in mafia_uids]

    # Rol taqsimotini guruhga e'lon qilish (kim qaysi roldayigi emas, faqat rollar soni)
    from collections import Counter
    dist_counter = Counter(r.value for r in assignment.values())
    dist_lines = []
    role_order = ["mafia", "don", "commissioner", "doctor", "maniac", "civilian"]
    for rv in role_order:
        if rv in dist_counter:
            r = ROLES[RoleType(rv)]
            dist_lines.append(f"{r.emoji} {r.name}: {dist_counter[rv]} ta")
    await message.answer(
        f"🎭 <b>O'yindagi rollar:</b>\n\n" + "\n".join(dist_lines) +
        "\n\n📨 Rollar tarqatilmoqda...",
        parse_mode="HTML"
    )

    # Har bir o'yinchiga lichkada rol yuborish
    failed: list[str] = []
    for p in players:
        role_type = assignment.get(p.user_id)
        if not role_type:
            logger.warning("No role in assignment for user %d (%s)", p.user_id, p.full_name)
            continue

        role = ROLES[role_type]
        text = (
            f"🎭 <b>Sizning rolingiz:</b>\n\n"
            f"{role.emoji} <b>{role.name}</b>\n\n"
            f"{role.description}"
        )

        # Mafiyalarga sheriklarini ko'rsatish
        if role_type in (RoleType.MAFIA, RoleType.DON) and len(mafia_players) > 1:
            mates = [m for m in mafia_players if m.user_id != p.user_id]
            mates_text = ", ".join(
                f"{player_mention(m)} ({ROLES[assignment[m.user_id]].emoji} {ROLES[assignment[m.user_id]].name})"
                for m in mates
            )
            text += f"\n\n🤝 <b>Mafiya sheriklari:</b> {mates_text}"

        try:
            await bot.send_message(p.user_id, text, parse_mode="HTML")
            logger.info("✅ Role sent: %s → %s (%s)", p.full_name, role_type.value, p.user_id)
        except (TelegramBadRequest, TelegramForbiddenError) as e:
            logger.warning("❌ Cannot send role to %s (%d): %s", p.full_name, p.user_id, e)
            failed.append(f'<a href="tg://user?id={p.user_id}">{html_module.escape(p.full_name)}</a>')

    if failed:
        await message.answer(
            f"⚠️ Quyidagilar rol ololmadi — avval "
            f"@Laminox_Mafia_bot ga /start bossin:\n"
            f"{', '.join(failed)}\n\n"
            f"<i>10 soniyadan keyin o'yin boshlanadi...</i>",
            parse_mode="HTML"
        )
        await asyncio.sleep(10)

    await _start_day_phase(message, bot, chat_id, round_number=1)


# ─── Kunduz bosqichi ──────────────────────────────────────────────────────────

async def _start_day_phase(message: Message, bot: Bot, chat_id: int, round_number: int):
    game = await db.get_game(chat_id)
    deadline = scheduler.deadline_iso(game.day_time)
    await db.update_game_state(chat_id, GameState.DAY_DISCUSSION,
                                phase_ends_at=deadline, round_number=round_number)
    await unlock_chat(bot, chat_id)

    alive = await db.get_players(chat_id, alive_only=True)
    mins = game.day_time // 60
    secs = game.day_time % 60
    time_str = f"{mins} daqiqa" + (f" {secs} soniya" if secs else "")

    await message.answer(
        f"☀️ <b>Kunduz — {round_number}-raund</b>\n\n"
        f"👥 Tirik o'yinchilar ({len(alive)} ta):\n"
        f"{format_player_list(alive)}\n\n"
        f"⏰ Muhokama vaqti: <b>{time_str}</b>\n"
        f"Gaplashing, muhokama qiling!",
        parse_mode="HTML"
    )

    scheduler.schedule(
        chat_id, game.day_time,
        lambda: _end_day_phase(message, bot, chat_id)
    )


async def _end_day_phase(message: Message, bot: Bot, chat_id: int):
    game = await db.get_game(chat_id)
    if not game or game.state != GameState.DAY_DISCUSSION:
        return

    await lock_chat(bot, chat_id)
    deadline = scheduler.deadline_iso(game.vote_time)
    await db.update_game_state(chat_id, GameState.DAY_VOTING, phase_ends_at=deadline)

    alive = await db.get_players(chat_id, alive_only=True)
    mins = game.vote_time // 60
    secs = game.vote_time % 60
    time_str = f"{mins} daqiqa" + (f" {secs} soniya" if secs else "")

    sent = await message.answer(
        f"🗳 <b>Ovoz berish!</b>\n\n"
        f"Kimni o'yindan chiqarasiz?\n"
        f"⏰ Vaqt: <b>{time_str}</b>",
        parse_mode="HTML"
    )

    # Har bir tirik o'yinchiga ovoz berish klaviaturasi
    for player in alive:
        try:
            await bot.send_message(
                player.user_id,
                f"🗳 <b>Ovoz berish vaqti!</b>\n"
                f"Kimni o'yindan chiqarmoqchisiz?\n"
                f"⏰ <b>{time_str}</b>",
                reply_markup=vote_keyboard(chat_id, alive, player.user_id),
                parse_mode="HTML"
            )
        except (TelegramBadRequest, TelegramForbiddenError):
            logger.warning("Cannot send vote keyboard to user %d", player.user_id)

    scheduler.schedule(
        chat_id, game.vote_time,
        lambda: _end_vote_phase(sent, bot, chat_id)
    )


# ─── Ovoz berish ──────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("vote:"))
async def cb_vote(call: CallbackQuery, bot: Bot):
    parts = call.data.split(":")
    chat_id = int(parts[1])
    target_id = int(parts[2])
    voter_id = call.from_user.id

    game = await db.get_game(chat_id)
    if not game or game.state != GameState.DAY_VOTING:
        await call.answer("❌ Hozir ovoz berish vaqti emas.", show_alert=True)
        return

    voter = await db.get_player(chat_id, voter_id)
    if not voter or not voter.is_alive:
        await call.answer("❌ Siz o'yinda yo'qsiz.", show_alert=True)
        return

    if await db.has_voted(game.id, game.round_number, voter_id):
        await call.answer("❌ Siz allaqachon ovoz berdingiz!", show_alert=True)
        return

    target = await db.get_player(chat_id, target_id)
    if not target or not target.is_alive:
        await call.answer("❌ Bu o'yinchi o'yinda emas.", show_alert=True)
        return

    await db.save_vote(game.id, chat_id, game.round_number, voter_id, target_id)
    await call.answer(f"✅ Ovoz berildi: {target.full_name}")

    try:
        await call.message.edit_text(
            f"✅ Siz <b>{html_module.escape(target.full_name)}</b> ga ovoz berdingiz.",
            parse_mode="HTML"
        )
    except TelegramBadRequest:
        pass

    await bot.send_message(
        chat_id,
        f"🗳 {player_mention(voter)} ovoz berdi.",
        parse_mode="HTML"
    )

    # Barcha tirik o'yinchilar ovoz berdimi?
    alive = await db.get_players(chat_id, alive_only=True)
    voted_count = 0
    for p in alive:
        if await db.has_voted(game.id, game.round_number, p.user_id):
            voted_count += 1
    if voted_count >= len(alive):
        scheduler.cancel(chat_id)
        sent = await bot.send_message(chat_id, "⚡ Barcha ovoz berdi!")
        await _end_vote_phase(sent, bot, chat_id)


@router.callback_query(F.data.startswith("skip_vote:"))
async def cb_skip_vote(call: CallbackQuery):
    chat_id = int(call.data.split(":")[1])
    voter_id = call.from_user.id
    game = await db.get_game(chat_id)
    if not game or game.state != GameState.DAY_VOTING:
        await call.answer("❌ Hozir ovoz berish vaqti emas.", show_alert=True)
        return

    if await db.has_voted(game.id, game.round_number, voter_id):
        await call.answer("Siz allaqachon ovoz berdingiz.", show_alert=True)
        return

    await db.save_vote(game.id, chat_id, game.round_number, voter_id, -1)
    await call.answer("⏭ O'tkazib yubordingiz.")
    try:
        await call.message.edit_text("⏭ Ovoz berishni o'tkazib yubordingiz.")
    except TelegramBadRequest:
        pass


async def _end_vote_phase(message: Message, bot: Bot, chat_id: int):
    game = await db.get_game(chat_id)
    if not game or game.state != GameState.DAY_VOTING:
        logger.warning("_end_vote_phase skipped: state=%s", game.state if game else "no game")
        return
    logger.info("Vote phase ending in chat %d round %d", chat_id, game.round_number)

    all_votes = await db.count_votes(game.id, game.round_number)
    real_votes = {uid: cnt for uid, cnt in all_votes.items() if uid != -1}

    if not real_votes:
        await message.answer(
            "🤔 <b>Hech kim ovoz bermadi.</b>\n"
            "O'yin davom etadi.",
            parse_mode="HTML"
        )
        await _start_night_phase(message, bot, chat_id)
        return

    max_votes = max(real_votes.values())
    leaders = [uid for uid, cnt in real_votes.items() if cnt == max_votes]

    # Ovoz jadvali
    players = await db.get_players(chat_id)
    player_map = {p.user_id: p for p in players}

    vote_lines = []
    for uid, cnt in sorted(real_votes.items(), key=lambda x: -x[1]):
        p = player_map.get(uid)
        if p:
            # player_mention HTML-safe, cnt oddiy int
            vote_lines.append(f"  {player_mention(p)}: <b>{cnt}</b> ta ovoz")

    vote_summary = "\n".join(vote_lines)

    if len(leaders) > 1:
        await message.answer(
            f"⚖️ <b>Ovoz berish natijasi:</b>\n\n"
            f"{vote_summary}\n\n"
            f"🤝 <b>Teng ovoz!</b> Hech kim chiqarilmadi.",
            parse_mode="HTML"
        )
        await _start_night_phase(message, bot, chat_id)
        return

    eliminated_id = leaders[0]
    eliminated = player_map.get(eliminated_id)
    await db.eliminate_player(chat_id, eliminated_id)

    role_info = ""
    if eliminated and eliminated.role:
        role = ROLES[eliminated.role]
        role_info = f"\n🎭 Roli: {role.emoji} <b>{role.name}</b>"

    await message.answer(
        f"⚖️ <b>Ovoz berish natijasi:</b>\n\n"
        f"{vote_summary}\n\n"
        f"💀 <b>{player_mention(eliminated)}</b> o'yindan chiqarildi! "
        f"({max_votes} ovoz){role_info}",
        parse_mode="HTML"
    )

    # Race condition oldini olish: state ni DISTRIBUTING ga o'tkazamiz
    # (shunday timer qaytadan _end_vote_phase chaqira olmaydi)
    await db.update_game_state(chat_id, GameState.DISTRIBUTING)

    # So'nggi so'z (30s) — eliminated bo'lsa
    if eliminated:
        await _give_last_words(bot, chat_id, [eliminated], message)

    # G'olibni tekshirish
    win = await check_win_condition(chat_id)
    if win:
        await _announce_winner(message, bot, chat_id, win)
        return

    # Tun bosqichiga o'tish
    await _start_night_phase(message, bot, chat_id)


# ─── So'nggi so'z ─────────────────────────────────────────────────────────────

LAST_WORDS_SECONDS = 30

async def _give_last_words(bot: Bot, chat_id: int,
                            dead_players: list, message: Message) -> None:
    """
    O'ldirilgan o'yinchilarga guruhda 30 soniya so'nggi so'z imkonini beradi.
    Shundan keyin ular kuzatuvchi bo'lib qoladi (guruhni o'qiy oladi, yoza olmaydi).
    """
    if not dead_players:
        return

    await unlock_chat(bot, chat_id)

    mentions = " ".join(player_mention(p) for p in dead_players)
    await message.answer(
        f"💀 {mentions}\n\n"
        f"⏳ <b>{LAST_WORDS_SECONDS} soniya — so'nggi so'zingizni ayting!</b>\n"
        f"Shundan keyin siz kuzatuvchi sifatida davom etasiz 👁",
        parse_mode="HTML"
    )

    await asyncio.sleep(LAST_WORDS_SECONDS)
    await lock_chat(bot, chat_id)


# ─── Tun bosqichi ─────────────────────────────────────────────────────────────

async def _start_night_phase(message: Message, bot: Bot, chat_id: int):
    # DISTRIBUTING yoki boshqa oraliq holatdan NIGHT ga o'tish
    game = await db.get_game(chat_id)
    if not game or game.state == GameState.GAME_OVER:
        return
    deadline = scheduler.deadline_iso(game.night_time)
    await db.update_game_state(chat_id, GameState.NIGHT, phase_ends_at=deadline)
    await lock_chat(bot, chat_id)

    alive = await db.get_players(chat_id, alive_only=True)
    actors = [p for p in alive if p.role and needs_night_action(p.role)]
    logger.info("Night %d started in chat %d | alive=%d actors=%d",
                game.round_number, chat_id, len(alive), len(actors))

    sent = await message.answer(
        f"🌙 <b>Tun — {game.round_number}-raund</b>\n\n"
        f"Shahar uxlayapti...\n"
        f"⏰ {game.night_time} soniya",
        parse_mode="HTML"
    )

    for player in alive:
        if not player.role or not needs_night_action(player.role):
            continue
        role = ROLES[player.role]
        action_type = get_night_action_type(player.role)
        targets = [p for p in alive if p.user_id != player.user_id]
        if not targets:
            continue
        try:
            await bot.send_message(
                player.user_id,
                f"🌙 <b>Tun {game.round_number}</b>\n\n{role.night_prompt}",
                reply_markup=night_action_keyboard(
                    chat_id, targets, player.user_id, action_type
                ),
                parse_mode="HTML"
            )
            logger.info("Night action sent to %s (%s)", player.full_name, role.name)
        except (TelegramBadRequest, TelegramForbiddenError) as e:
            logger.warning("Cannot send night action to %s: %s", player.full_name, e)

    scheduler.schedule(
        chat_id, game.night_time,
        lambda: _end_night_phase(sent, bot, chat_id)
    )


async def _end_night_phase(message: Message, bot: Bot, chat_id: int):
    game = await db.get_game(chat_id)
    if not game or game.state != GameState.NIGHT:
        logger.warning("_end_night_phase skipped: state=%s", game.state if game else "no game")
        return

    logger.info("Night %d ending in chat %d", game.round_number, chat_id)
    from game_engine import resolve_night
    result = await resolve_night(game)

    all_dead = result.killed + result.maniac_killed
    for uid in all_dead:
        await db.eliminate_player(chat_id, uid)

    players = await db.get_players(chat_id)
    player_map = {p.user_id: p for p in players}

    lines = ["🌅 <b>Tong otdi.</b>\n"]

    if not all_dead and not result.saved:
        lines.append("😮 Kechasi hech kim o'lmadi.")
    else:
        for uid in result.killed:
            p = player_map.get(uid)
            if p:
                role = ROLES[p.role] if p.role else None
                role_txt = f" ({role.emoji} {role.name})" if role else ""
                lines.append(f"💀 {player_mention(p)}{role_txt} o'ldirildi.")

        for uid in result.maniac_killed:
            p = player_map.get(uid)
            if p:
                role = ROLES[p.role] if p.role else None
                role_txt = f" ({role.emoji} {role.name})" if role else ""
                lines.append(f"🔪 {player_mention(p)}{role_txt} noma'lum shaxs tomonidan o'ldirildi.")

        for uid in result.saved:
            p = player_map.get(uid)
            if p:
                lines.append(f"💊 {player_mention(p)} omon qoldi!")

    # Komissarga natija (shaxsiy xabar)
    for uid, is_mafia in result.checked.items():
        checked_p = player_map.get(uid)
        if not checked_p:
            continue
        for p in players:
            if p.role == RoleType.COMMISSIONER and p.is_alive:
                status = "🔴 Mafiya tomoni" if is_mafia else "🟢 Tinch aholi"
                try:
                    await bot.send_message(
                        p.user_id,
                        f"🔍 <b>Tekshiruv natijasi:</b>\n"
                        f"{player_mention(checked_p)} — {status}",
                        parse_mode="HTML"
                    )
                except (TelegramBadRequest, TelegramForbiddenError):
                    pass

    await message.answer("\n".join(lines), parse_mode="HTML")

    # Race condition oldini olish: state DISTRIBUTING ga o'tadi
    await db.update_game_state(chat_id, GameState.DISTRIBUTING)

    # O'lgan o'yinchilarga so'nggi so'z imkoni
    dead_players = [player_map[uid] for uid in all_dead if uid in player_map]
    if dead_players:
        await _give_last_words(bot, chat_id, dead_players, message)

    # G'olibni tekshirish
    win = await check_win_condition(chat_id)
    if win:
        await _announce_winner(message, bot, chat_id, win)
        return

    new_round = game.round_number + 1
    await _start_day_phase(message, bot, chat_id, round_number=new_round)


# ─── G'olibni e'lon qilish ────────────────────────────────────────────────────

async def _announce_winner(message: Message, bot: Bot, chat_id: int, win):
    logger.info("Game over in chat %d | winner: %s | reason: %s",
                chat_id, win.winner, win.reason)
    await db.update_game_state(chat_id, GameState.GAME_OVER)
    await unlock_chat(bot, chat_id)
    scheduler.cancel(chat_id)

    winner_texts = {
        "town":   "🏙 <b>SHAHAR G'ALABA QOZONDI!</b>\nMafiya mag'lub bo'ldi!",
        "mafia":  "🔫 <b>MAFIYA G'ALABA QOZONDI!</b>\nShahar boshqarildi!",
        "maniac": "🔪 <b>MANYAK G'ALABA QOZONDI!</b>\nHamma yo'q qilindi!",
    }
    header = winner_texts.get(win.winner, "🏁 O'yin tugadi!")

    # O'yinchilar ro'yxatini xavfsiz tuzish
    try:
        all_players = await db.get_players(chat_id)
        lines = []
        for i, p in enumerate(all_players, 1):
            status = "✅" if p.is_alive else "💀"
            name = player_mention(p)
            if p.role:
                try:
                    role = ROLES[p.role]
                    lines.append(f"{i}. {status} {name} — {role.emoji} {role.name}")
                except Exception:
                    lines.append(f"{i}. {status} {name}")
            else:
                lines.append(f"{i}. {status} {name}")
        roles_text = "\n".join(lines) if lines else "—"
    except Exception as e:
        logger.error("get_players failed in _announce_winner: %s", e)
        roles_text = "—"

    body = (
        f"{header}\n\n"
        f"📋 {html_module.escape(win.reason)}\n\n"
        f"<b>Barcha o'yinchilar:</b>\n{roles_text}\n\n"
        f"Yangi o'yin: /newgame"
    )

    # bot.send_message — message.answer ga qaraganda ishonchliroq
    try:
        await bot.send_message(chat_id, body, parse_mode="HTML")
        logger.info("Winner announcement sent to chat %d", chat_id)
    except Exception as e:
        logger.error("HTML announcement failed (%s), trying plain text", e)
        try:
            plain = (
                f"🏁 O'yin tugadi! G'olib: {win.winner}\n"
                f"{win.reason}\n\nYangi o'yin: /newgame"
            )
            await bot.send_message(chat_id, plain)
            logger.info("Plain text announcement sent to chat %d", chat_id)
        except Exception as e2:
            logger.error("All announcements failed for chat %d: %s", chat_id, e2)


# ─── O'yinni bekor qilish callback ───────────────────────────────────────────

@router.callback_query(F.data.startswith("cancelgame:"))
async def cb_cancel_game(call: CallbackQuery, bot: Bot):
    chat_id = int(call.data.split(":")[1])
    if not await _is_admin(bot, chat_id, call.from_user.id):
        await call.answer("❌ Faqat admin.", show_alert=True)
        return

    game = await db.get_game(chat_id)
    if not game or game.state in (GameState.IDLE, GameState.GAME_OVER):
        await call.answer("Faol o'yin yo'q.", show_alert=True)
        return

    scheduler.cancel(chat_id)
    await db.update_game_state(chat_id, GameState.GAME_OVER)
    await unlock_chat(bot, chat_id)

    await call.answer("✅ Bekor qilindi.")
    try:
        await call.message.edit_reply_markup(reply_markup=None)
    except TelegramBadRequest:
        pass
    await call.message.answer("🛑 O'yin bekor qilindi. /newgame")


# ─── Yordamchi ────────────────────────────────────────────────────────────────

async def _is_admin(bot: Bot, chat_id: int, user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        return member.status in ("administrator", "creator")
    except Exception:
        return False


async def _is_creator_or_admin(bot: Bot, chat_id: int, user_id: int,
                                game: db.Game | None) -> bool:
    """O'yin yaratgan odam yoki guruh admini."""
    # DB dagi o'yinda created_by tekshirish
    if game and game.created_by == user_id:
        return True
    # _setup dagi wizard creator tekshirish (game yaratilmagan paytda)
    from handlers.commands import get_setup_creator
    if get_setup_creator(chat_id) == user_id and user_id != 0:
        return True
    return await _is_admin(bot, chat_id, user_id)
