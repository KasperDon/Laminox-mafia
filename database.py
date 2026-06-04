import aiosqlite
import json
import logging
from datetime import datetime
from typing import Optional
from dataclasses import dataclass

from config import settings
from roles import RoleType, GameState

logger = logging.getLogger(__name__)

# ─── Data classes ─────────────────────────────────────────────────────────────

@dataclass
class Game:
    id: int
    chat_id: int
    state: GameState
    round_number: int
    phase_ends_at: Optional[str]
    day_time: int
    vote_time: int
    night_time: int
    created_by: int
    created_at: str


@dataclass
class Player:
    id: int
    game_id: int
    chat_id: int
    user_id: int
    username: Optional[str]
    full_name: str
    role: Optional[RoleType]
    is_alive: bool


@dataclass
class NightAction:
    id: int
    game_id: int
    chat_id: int
    round_number: int
    actor_user_id: int
    target_user_id: Optional[int]
    action_type: str  # "kill", "heal", "check", "maniac_kill"


@dataclass
class VoteAction:
    id: int
    game_id: int
    chat_id: int
    round_number: int
    voter_user_id: int
    target_user_id: int


# ─── Init ─────────────────────────────────────────────────────────────────────

async def init_db() -> None:
    # DB papkasi mavjud bo'lmasa yaratish (Railway volume uchun)
    import os
    db_dir = os.path.dirname(settings.DATABASE_PATH)
    if db_dir and not os.path.exists(db_dir):
        os.makedirs(db_dir, exist_ok=True)
        logger.info("Created database directory: %s", db_dir)

    async with aiosqlite.connect(settings.DATABASE_PATH) as db:
        # WAL mode — bir vaqtda ko'p connection muammosini hal qiladi
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA synchronous=NORMAL")
        await db.commit()
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS games (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id         INTEGER UNIQUE NOT NULL,
                state           TEXT    NOT NULL DEFAULT 'idle',
                round_number    INTEGER NOT NULL DEFAULT 0,
                phase_ends_at   TEXT,
                day_time        INTEGER NOT NULL DEFAULT 300,
                vote_time       INTEGER NOT NULL DEFAULT 120,
                night_time      INTEGER NOT NULL DEFAULT 60,
                created_by      INTEGER,
                created_at      TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS players (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                game_id     INTEGER NOT NULL,
                chat_id     INTEGER NOT NULL,
                user_id     INTEGER NOT NULL,
                username    TEXT,
                full_name   TEXT    NOT NULL,
                role        TEXT,
                is_alive    INTEGER NOT NULL DEFAULT 1,
                joined_at   TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (game_id) REFERENCES games(id) ON DELETE CASCADE,
                UNIQUE(game_id, user_id)
            );

            CREATE TABLE IF NOT EXISTS night_actions (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                game_id         INTEGER NOT NULL,
                chat_id         INTEGER NOT NULL,
                round_number    INTEGER NOT NULL,
                actor_user_id   INTEGER NOT NULL,
                target_user_id  INTEGER,
                action_type     TEXT    NOT NULL,
                created_at      TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (game_id) REFERENCES games(id) ON DELETE CASCADE,
                UNIQUE(game_id, round_number, actor_user_id)
            );

            CREATE TABLE IF NOT EXISTS vote_actions (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                game_id         INTEGER NOT NULL,
                chat_id         INTEGER NOT NULL,
                round_number    INTEGER NOT NULL,
                voter_user_id   INTEGER NOT NULL,
                target_user_id  INTEGER NOT NULL,
                created_at      TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (game_id) REFERENCES games(id) ON DELETE CASCADE,
                UNIQUE(game_id, round_number, voter_user_id)
            );

            CREATE INDEX IF NOT EXISTS idx_players_chat_user
                ON players(chat_id, user_id);

            CREATE INDEX IF NOT EXISTS idx_night_actions_game_round
                ON night_actions(game_id, round_number);
        """)
        await db.commit()
    logger.info("Database initialized: %s", settings.DATABASE_PATH)


# ─── Game repository ───────────────────────────────────────────────────────────

def _row_to_game(row: aiosqlite.Row) -> Game:
    return Game(
        id=row[0], chat_id=row[1], state=GameState(row[2]),
        round_number=row[3], phase_ends_at=row[4],
        day_time=row[5], vote_time=row[6], night_time=row[7],
        created_by=row[8], created_at=row[9],
    )


async def get_game(chat_id: int) -> Optional[Game]:
    async with aiosqlite.connect(settings.DATABASE_PATH) as db:
        async with db.execute(
            "SELECT id,chat_id,state,round_number,phase_ends_at,"
            "day_time,vote_time,night_time,created_by,created_at "
            "FROM games WHERE chat_id=?", (chat_id,)
        ) as cur:
            row = await cur.fetchone()
            return _row_to_game(row) if row else None


async def get_active_games() -> list[Game]:
    """Barcha faol o'yinlarni qaytaradi (restart uchun)."""
    async with aiosqlite.connect(settings.DATABASE_PATH) as db:
        async with db.execute(
            "SELECT id,chat_id,state,round_number,phase_ends_at,"
            "day_time,vote_time,night_time,created_by,created_at "
            "FROM games WHERE state NOT IN ('idle','game_over')"
        ) as cur:
            rows = await cur.fetchall()
            return [_row_to_game(r) for r in rows]


async def create_game(chat_id: int, created_by: int, day_time: int,
                      vote_time: int, night_time: int) -> Game:
    async with aiosqlite.connect(settings.DATABASE_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO games "
            "(chat_id,state,round_number,day_time,vote_time,night_time,created_by) "
            "VALUES (?,?,0,?,?,?,?)",
            (chat_id, GameState.WAITING, day_time, vote_time, night_time, created_by)
        )
        await db.commit()
    return await get_game(chat_id)


async def update_game_state(chat_id: int, state: GameState,
                             phase_ends_at: Optional[str] = None,
                             round_number: Optional[int] = None) -> None:
    async with aiosqlite.connect(settings.DATABASE_PATH) as db:
        if round_number is not None:
            await db.execute(
                "UPDATE games SET state=?, phase_ends_at=?, round_number=? WHERE chat_id=?",
                (state, phase_ends_at, round_number, chat_id)
            )
        else:
            await db.execute(
                "UPDATE games SET state=?, phase_ends_at=? WHERE chat_id=?",
                (state, phase_ends_at, chat_id)
            )
        await db.commit()


async def update_game_settings(chat_id: int, day_time: Optional[int] = None,
                                vote_time: Optional[int] = None,
                                night_time: Optional[int] = None) -> None:
    async with aiosqlite.connect(settings.DATABASE_PATH) as db:
        if day_time is not None:
            await db.execute("UPDATE games SET day_time=? WHERE chat_id=?", (day_time, chat_id))
        if vote_time is not None:
            await db.execute("UPDATE games SET vote_time=? WHERE chat_id=?", (vote_time, chat_id))
        if night_time is not None:
            await db.execute("UPDATE games SET night_time=? WHERE chat_id=?", (night_time, chat_id))
        await db.commit()


async def delete_game(chat_id: int) -> None:
    async with aiosqlite.connect(settings.DATABASE_PATH) as db:
        await db.execute("DELETE FROM games WHERE chat_id=?", (chat_id,))
        await db.commit()


# ─── Player repository ────────────────────────────────────────────────────────

def _row_to_player(row: aiosqlite.Row) -> Player:
    return Player(
        id=row[0], game_id=row[1], chat_id=row[2], user_id=row[3],
        username=row[4], full_name=row[5],
        role=RoleType(row[6]) if row[6] else None,
        is_alive=bool(row[7]),
    )


async def add_player(game_id: int, chat_id: int, user_id: int,
                     username: Optional[str], full_name: str) -> bool:
    """O'yinchini qo'shadi. Agar allaqachon bor bo'lsa False qaytaradi."""
    try:
        async with aiosqlite.connect(settings.DATABASE_PATH) as db:
            await db.execute(
                "INSERT INTO players (game_id,chat_id,user_id,username,full_name) "
                "VALUES (?,?,?,?,?)",
                (game_id, chat_id, user_id, username, full_name)
            )
            await db.commit()
        return True
    except aiosqlite.IntegrityError:
        return False


async def get_players(chat_id: int, alive_only: bool = False) -> list[Player]:
    async with aiosqlite.connect(settings.DATABASE_PATH) as db:
        # game_id ni bitta connection ichida olish
        async with db.execute(
            "SELECT id FROM games WHERE chat_id=?", (chat_id,)
        ) as cur:
            row = await cur.fetchone()
            if not row:
                return []
            game_id = row[0]

        query = (
            "SELECT id,game_id,chat_id,user_id,username,full_name,role,is_alive "
            "FROM players WHERE game_id=?"
        )
        params = [game_id]
        if alive_only:
            query += " AND is_alive=1"
        async with db.execute(query, params) as cur:
            rows = await cur.fetchall()
            return [_row_to_player(r) for r in rows]


async def get_player(chat_id: int, user_id: int) -> Optional[Player]:
    async with aiosqlite.connect(settings.DATABASE_PATH) as db:
        async with db.execute(
            "SELECT p.id,p.game_id,p.chat_id,p.user_id,p.username,p.full_name,p.role,p.is_alive "
            "FROM players p JOIN games g ON p.game_id=g.id "
            "WHERE g.chat_id=? AND p.user_id=?",
            (chat_id, user_id)
        ) as cur:
            row = await cur.fetchone()
            return _row_to_player(row) if row else None


async def get_player_by_user_id(user_id: int) -> Optional[Player]:
    """Foydalanuvchining faol o'yinini topadi (private chat uchun)."""
    async with aiosqlite.connect(settings.DATABASE_PATH) as db:
        async with db.execute(
            "SELECT p.id,p.game_id,p.chat_id,p.user_id,p.username,p.full_name,p.role,p.is_alive "
            "FROM players p JOIN games g ON p.game_id=g.id "
            "WHERE p.user_id=? AND g.state NOT IN ('idle','game_over','waiting','role_confirmation') "
            "AND p.is_alive=1",
            (user_id,)
        ) as cur:
            row = await cur.fetchone()
            return _row_to_player(row) if row else None


async def set_player_role(game_id: int, user_id: int, role: RoleType) -> None:
    async with aiosqlite.connect(settings.DATABASE_PATH) as db:
        await db.execute(
            "UPDATE players SET role=? WHERE game_id=? AND user_id=?",
            (role.value, game_id, user_id)   # to'g'ri tartib: role, game_id, user_id
        )
        await db.commit()


async def set_all_player_roles(game_id: int,
                                assignment: dict[int, RoleType]) -> None:
    """Barcha rollarni bitta tranzaksiyada saqlaydi (ishonchli)."""
    async with aiosqlite.connect(settings.DATABASE_PATH) as db:
        for user_id, role in assignment.items():
            await db.execute(
                "UPDATE players SET role=? WHERE game_id=? AND user_id=?",
                (role.value, game_id, user_id)  # to'g'ri tartib: role, game_id, user_id
            )
        await db.commit()


async def eliminate_player(chat_id: int, user_id: int) -> None:
    async with aiosqlite.connect(settings.DATABASE_PATH) as db:
        await db.execute(
            "UPDATE players SET is_alive=0 "
            "WHERE game_id=(SELECT id FROM games WHERE chat_id=?) AND user_id=?",
            (chat_id, user_id)
        )
        await db.commit()


async def clear_players(game_id: int) -> None:
    async with aiosqlite.connect(settings.DATABASE_PATH) as db:
        await db.execute("DELETE FROM players WHERE game_id=?", (game_id,))
        await db.commit()


# ─── Night actions repository ─────────────────────────────────────────────────

async def save_night_action(game_id: int, chat_id: int, round_number: int,
                             actor_user_id: int, target_user_id: Optional[int],
                             action_type: str) -> None:
    async with aiosqlite.connect(settings.DATABASE_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO night_actions "
            "(game_id,chat_id,round_number,actor_user_id,target_user_id,action_type) "
            "VALUES (?,?,?,?,?,?)",
            (game_id, chat_id, round_number, actor_user_id, target_user_id, action_type)
        )
        await db.commit()


async def get_night_actions(game_id: int, round_number: int) -> list[NightAction]:
    async with aiosqlite.connect(settings.DATABASE_PATH) as db:
        async with db.execute(
            "SELECT id,game_id,chat_id,round_number,actor_user_id,target_user_id,action_type "
            "FROM night_actions WHERE game_id=? AND round_number=?",
            (game_id, round_number)
        ) as cur:
            rows = await cur.fetchall()
            return [NightAction(*r) for r in rows]


async def has_night_action(game_id: int, round_number: int, actor_user_id: int) -> bool:
    async with aiosqlite.connect(settings.DATABASE_PATH) as db:
        async with db.execute(
            "SELECT 1 FROM night_actions WHERE game_id=? AND round_number=? AND actor_user_id=?",
            (game_id, round_number, actor_user_id)
        ) as cur:
            return await cur.fetchone() is not None


# ─── Vote repository ──────────────────────────────────────────────────────────

async def save_vote(game_id: int, chat_id: int, round_number: int,
                    voter_user_id: int, target_user_id: int) -> bool:
    """Ovozni saqlaydi. Agar allaqachon ovoz bergan bo'lsa False qaytaradi."""
    try:
        async with aiosqlite.connect(settings.DATABASE_PATH) as db:
            await db.execute(
                "INSERT INTO vote_actions (game_id,chat_id,round_number,voter_user_id,target_user_id) "
                "VALUES (?,?,?,?,?)",
                (game_id, chat_id, round_number, voter_user_id, target_user_id)
            )
            await db.commit()
        return True
    except aiosqlite.IntegrityError:
        return False


async def get_votes(game_id: int, round_number: int) -> list[VoteAction]:
    async with aiosqlite.connect(settings.DATABASE_PATH) as db:
        async with db.execute(
            "SELECT id,game_id,chat_id,round_number,voter_user_id,target_user_id "
            "FROM vote_actions WHERE game_id=? AND round_number=?",
            (game_id, round_number)
        ) as cur:
            rows = await cur.fetchall()
            return [VoteAction(*r) for r in rows]


async def count_votes(game_id: int, round_number: int) -> dict[int, int]:
    """user_id -> ovozlar soni."""
    votes = await get_votes(game_id, round_number)
    result: dict[int, int] = {}
    for v in votes:
        result[v.target_user_id] = result.get(v.target_user_id, 0) + 1
    return result


async def has_voted(game_id: int, round_number: int, voter_user_id: int) -> bool:
    async with aiosqlite.connect(settings.DATABASE_PATH) as db:
        async with db.execute(
            "SELECT 1 FROM vote_actions WHERE game_id=? AND round_number=? AND voter_user_id=?",
            (game_id, round_number, voter_user_id)
        ) as cur:
            return await cur.fetchone() is not None
