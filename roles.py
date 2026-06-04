from enum import Enum
from dataclasses import dataclass


class RoleType(str, Enum):
    CIVILIAN = "civilian"
    MAFIA = "mafia"
    DON = "don"
    COMMISSIONER = "commissioner"
    DOCTOR = "doctor"
    MANIAC = "maniac"


class Team(str, Enum):
    TOWN = "town"
    MAFIA = "mafia"
    NEUTRAL = "neutral"


class GameState(str, Enum):
    IDLE = "idle"
    WAITING = "waiting"
    ROLE_CONFIRMATION = "role_confirmation"
    DISTRIBUTING = "distributing"
    DAY_DISCUSSION = "day_discussion"
    DAY_VOTING = "day_voting"
    NIGHT = "night"
    GAME_OVER = "game_over"


@dataclass(frozen=True)
class Role:
    type: RoleType
    name: str
    emoji: str
    team: Team
    description: str
    night_action: bool
    night_prompt: str = ""


ROLES: dict[RoleType, Role] = {
    RoleType.CIVILIAN: Role(
        type=RoleType.CIVILIAN,
        name="Tinch aholi",
        emoji="👤",
        team=Team.TOWN,
        description="Mafia kimligini topib, ularni ovoz berish orqali o'yindan chiqaring.",
        night_action=False,
    ),
    RoleType.MAFIA: Role(
        type=RoleType.MAFIA,
        name="Mafiya",
        emoji="🔫",
        team=Team.MAFIA,
        description="Tunda bir odamni o'ldiring. Kunduzi o'zingizni yashiring.",
        night_action=True,
        night_prompt="🔫 Kimni o'ldirasiz? Qurboningizni tanlang:",
    ),
    RoleType.DON: Role(
        type=RoleType.DON,
        name="Don",
        emoji="👑",
        team=Team.MAFIA,
        description="Mafiya boshlig'i. Mafiya bilan birga qurbon tanlaysiz.",
        night_action=True,
        night_prompt="👑 Don sifatida kimni o'ldirishni tanlaysiz?",
    ),
    RoleType.COMMISSIONER: Role(
        type=RoleType.COMMISSIONER,
        name="Komissar",
        emoji="🔍",
        team=Team.TOWN,
        description="Tunda bir odamni tekshirasiz: mafiyami yoki tinchmi.",
        night_action=True,
        night_prompt="🔍 Kimni tekshirasiz?",
    ),
    RoleType.DOCTOR: Role(
        type=RoleType.DOCTOR,
        name="Doktor",
        emoji="💊",
        team=Team.TOWN,
        description="Tunda bir odamni davolaysiz. Davolangan odam o'lmaydi.",
        night_action=True,
        night_prompt="💊 Kimni davolaysiz?",
    ),
    RoleType.MANIAC: Role(
        type=RoleType.MANIAC,
        name="Manyak",
        emoji="🔪",
        team=Team.NEUTRAL,
        description="Yakka o'ynaysiz. Tunda bir odamni o'ldirasiz. Yolg'iz qolsangiz g'olib bo'lasiz.",
        night_action=True,
        night_prompt="🔪 Kimni o'ldirasiz?",
    ),
}


def get_role_distribution(player_count: int) -> dict[RoleType, int]:
    """O'yinchi soniga qarab rol taqsimotini qaytaradi."""
    if player_count <= 6:
        return {
            RoleType.MAFIA: 1,
            RoleType.COMMISSIONER: 1,
            RoleType.DOCTOR: 1,
            RoleType.CIVILIAN: player_count - 3,
        }
    elif player_count <= 9:
        return {
            RoleType.MAFIA: 2,
            RoleType.COMMISSIONER: 1,
            RoleType.DOCTOR: 1,
            RoleType.CIVILIAN: player_count - 4,
        }
    elif player_count <= 11:
        return {
            RoleType.MAFIA: 2,
            RoleType.DON: 1,
            RoleType.COMMISSIONER: 1,
            RoleType.DOCTOR: 1,
            RoleType.CIVILIAN: player_count - 5,
        }
    else:  # 12+
        return {
            RoleType.MAFIA: 3,
            RoleType.DON: 1,
            RoleType.COMMISSIONER: 1,
            RoleType.DOCTOR: 1,
            RoleType.MANIAC: 1,
            RoleType.CIVILIAN: player_count - 7,
        }


def format_distribution(dist: dict[RoleType, int]) -> str:
    lines = []
    for role_type, count in dist.items():
        role = ROLES[role_type]
        lines.append(f"  {role.emoji} {role.name}: {count} ta")
    return "\n".join(lines)
