"""
O'yinning asosiy mantiqiy qismi: rollar taqsimlash, tun harakatlarini hisoblash,
g'olib aniqlash.
"""
import html
import random
import logging
from collections import Counter

from roles import RoleType, Team, ROLES, get_role_distribution
from database import (
    Game, Player, NightAction,
    get_players, eliminate_player, set_all_player_roles,
    get_night_actions, count_votes,
)

logger = logging.getLogger(__name__)

MIN_PLAYERS = 5


# ─── Rollar taqsimlash ────────────────────────────────────────────────────────

async def assign_roles(game: Game,
                        custom_dist: dict[RoleType, int] | None = None
                        ) -> dict[int, RoleType]:
    """
    O'yinchilarga rollarni tasodifiy taqsimlaydi.
    Qaytaradi: {user_id: RoleType}
    """
    players = await get_players(game.chat_id)
    if not players:
        return {}

    dist = custom_dist or get_role_distribution(len(players))

    role_list: list[RoleType] = []
    for role_type, count in dist.items():
        role_list.extend([role_type] * count)

    # Agar odam soni bilan rol soni mos kelmasa to'ldirish
    while len(role_list) < len(players):
        role_list.append(RoleType.CIVILIAN)

    random.shuffle(role_list)

    assignment: dict[int, RoleType] = {}
    for player, role_type in zip(players, role_list):
        assignment[player.user_id] = role_type

    # Barcha rollarni bitta tranzaksiyada yozamiz
    await set_all_player_roles(game.id, assignment)

    logger.info("Roles assigned in chat %d: %s", game.chat_id,
                {k: v.value for k, v in assignment.items()})
    return assignment


# ─── Tun natijalarini hisoblash ───────────────────────────────────────────────

class NightResult:
    def __init__(self):
        self.killed: list[int] = []          # o'ldirilgan user_id lar
        self.healed: list[int] = []          # davolangan user_id lar
        self.saved: list[int] = []           # o'limdan qutulgan user_id lar
        self.checked: dict[int, bool] = {}   # {user_id: is_mafia}
        self.maniac_killed: list[int] = []   # manyak o'ldirgan


async def resolve_night(game: Game) -> NightResult:
    """
    Tun harakatlarini qayta ishlaydi va NightResult qaytaradi.
    Hali eliminate_player chaqirmaydi — bu handler'da amalga oshiriladi.
    """
    actions = await get_night_actions(game.id, game.round_number)
    players = await get_players(game.chat_id, alive_only=True)
    player_map = {p.user_id: p for p in players}

    result = NightResult()

    mafia_targets: list[int] = []
    maniac_target: int | None = None
    heal_target: int | None = None

    for action in actions:
        t = action.target_user_id
        if action.action_type in ("kill",) and t:
            mafia_targets.append(t)
        elif action.action_type == "maniac_kill" and t:
            maniac_target = t
        elif action.action_type == "heal" and t:
            heal_target = t
        elif action.action_type == "check" and t:
            p = player_map.get(t)
            if p and p.role:
                is_mafia = ROLES[p.role].team == Team.MAFIA
                result.checked[t] = is_mafia

    # Mafiya – ko'pchilik ovoz bergan qurbonni o'ldiradi
    if mafia_targets:
        target = Counter(mafia_targets).most_common(1)[0][0]
        if heal_target == target:
            result.saved.append(target)
        else:
            result.killed.append(target)

    # Manyak alohida o'ldiradi
    if maniac_target:
        if heal_target == maniac_target:
            result.saved.append(maniac_target)
        else:
            result.maniac_killed.append(maniac_target)

    if heal_target:
        result.healed.append(heal_target)

    return result


# ─── G'olib tekshirish ────────────────────────────────────────────────────────

class WinResult:
    def __init__(self, winner: str | None, reason: str):
        self.winner = winner   # "town", "mafia", "maniac", None
        self.reason = reason


async def check_win_condition(chat_id: int) -> WinResult | None:
    """
    G'olib bo'lsa WinResult qaytaradi, o'yin davom etsa None.
    """
    players = await get_players(chat_id, alive_only=True)

    mafia_count = sum(
        1 for p in players
        if p.role and ROLES[p.role].team == Team.MAFIA
    )
    town_count = sum(
        1 for p in players
        if p.role and ROLES[p.role].team == Team.TOWN
    )
    maniac_alive = any(p.role == RoleType.MANIAC for p in players)
    total = len(players)

    # Mafiya yo'q → shahar yutadi
    if mafia_count == 0 and not maniac_alive:
        return WinResult("town", "Barcha mafiyalar o'yindan chiqarildi!")

    if mafia_count == 0 and maniac_alive:
        if total == 1:
            return WinResult("maniac", "Manyak yolg'iz qoldi va g'alaba qozondi!")
        # Mafiya yo'q, manyak bor, shahar bor → o'yin davom etadi

    # Mafiya ≥ tinch aholi → mafiya yutadi
    if mafia_count >= town_count + (1 if maniac_alive else 0):
        return WinResult("mafia", "Mafiya ko'pchilikni egalladi!")

    # Manyak yolg'iz qolsa
    if maniac_alive and total == 1:
        return WinResult("maniac", "Manyak yolg'iz qoldi va g'alaba qozondi!")

    return None


# ─── Ovoz berish natijasi ─────────────────────────────────────────────────────

async def resolve_vote(game: Game) -> tuple[int | None, bool]:
    """
    Ovoz natijasini hisoblaydi.
    Qaytaradi: (chiqarilgan_user_id | None, teng_ovoz_bo'ldimi)
    """
    votes = await count_votes(game.id, game.round_number)
    if not votes:
        return None, False

    max_votes = max(votes.values())
    leaders = [uid for uid, cnt in votes.items() if cnt == max_votes]

    if len(leaders) > 1:
        return None, True  # teng ovoz

    return leaders[0], False


# ─── Yordamchi funksiyalar ────────────────────────────────────────────────────

def format_player_list(players: list[Player], show_roles: bool = False) -> str:
    lines = []
    for i, p in enumerate(players, 1):
        status = "✅" if p.is_alive else "💀"
        name = player_mention(p)
        if show_roles and p.role:
            role = ROLES[p.role]
            lines.append(f"{i}. {status} {name} — {role.emoji} {role.name}")
        else:
            lines.append(f"{i}. {status} {name}")
    return "\n".join(lines) if lines else "— hech kim yo'q —"


def player_mention(player: Player) -> str:
    """HTML mention formati. Ismni HTML-escape qiladi (< > & belgilar uchun)."""
    safe_name = html.escape(player.full_name)
    return f'<a href="tg://user?id={player.user_id}">{safe_name}</a>'


def needs_night_action(role: RoleType) -> bool:
    return ROLES[role].night_action


def get_night_action_type(role: RoleType) -> str:
    mapping = {
        RoleType.MAFIA: "kill",
        RoleType.DON: "kill",
        RoleType.DOCTOR: "heal",
        RoleType.COMMISSIONER: "check",
        RoleType.MANIAC: "maniac_kill",
    }
    return mapping.get(role, "")
