import time

import aiosqlite

from config import DB_PATH, USER_QUESTIONS_LIMIT


def _connect() -> aiosqlite.Connection:
    return aiosqlite.connect(DB_PATH)


async def init_db() -> None:
    async with _connect() as db:
        await db.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                full_name TEXT,
                is_authorized INTEGER DEFAULT 0,
                joined_at REAL
            );
            CREATE TABLE IF NOT EXISTS questions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                username TEXT,
                full_name TEXT,
                question_text TEXT,
                answer_text TEXT,
                is_anonymous INTEGER DEFAULT 0,
                status TEXT DEFAULT 'open',
                created_at REAL,
                answered_at REAL
            );
            CREATE INDEX IF NOT EXISTS idx_questions_user ON questions(user_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_questions_status ON questions(status, created_at);
            CREATE TABLE IF NOT EXISTS training_signups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                training_id TEXT NOT NULL,
                user_id INTEGER NOT NULL,
                username TEXT,
                full_name TEXT,
                is_admin INTEGER DEFAULT 0,
                created_at REAL
            );
            CREATE INDEX IF NOT EXISTS idx_signups_user
                ON training_signups(user_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_signups_training
                ON training_signups(training_id, created_at);
            """
        )

        # ---- Migrations for evolving training_signups schema ----
        # 1. Добавить колонку is_admin, если её нет (от старой версии схемы).
        cursor = await db.execute("PRAGMA table_info(training_signups)")
        columns = {row[1] for row in await cursor.fetchall()}
        if "is_admin" not in columns:
            await db.execute(
                "ALTER TABLE training_signups ADD COLUMN is_admin INTEGER DEFAULT 0"
            )

        # 2. Снять UNIQUE(training_id, user_id), если он есть.
        #    Это нужно чтобы админ мог делать несколько тест-записей в одну группу.
        cursor = await db.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='training_signups'"
        )
        row = await cursor.fetchone()
        if row and "UNIQUE" in (row[0] or "").upper():
            await db.executescript(
                """
                CREATE TABLE training_signups_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    training_id TEXT NOT NULL,
                    user_id INTEGER NOT NULL,
                    username TEXT,
                    full_name TEXT,
                    is_admin INTEGER DEFAULT 0,
                    created_at REAL
                );
                INSERT INTO training_signups_new
                    (id, training_id, user_id, username, full_name, is_admin, created_at)
                    SELECT id, training_id, user_id, username, full_name,
                           COALESCE(is_admin, 0), created_at
                    FROM training_signups;
                DROP TABLE training_signups;
                ALTER TABLE training_signups_new RENAME TO training_signups;
                CREATE INDEX IF NOT EXISTS idx_signups_user
                    ON training_signups(user_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_signups_training
                    ON training_signups(training_id, created_at);
                """
            )

        await db.commit()


# Users

async def add_user(user_id: int, username: str, full_name: str) -> None:
    async with _connect() as db:
        await db.execute(
            "INSERT OR IGNORE INTO users (user_id, username, full_name, joined_at) "
            "VALUES (?, ?, ?, ?)",
            (user_id, username, full_name, time.time()),
        )
        await db.commit()


async def is_user_authorized(user_id: int) -> bool:
    async with _connect() as db:
        cursor = await db.execute(
            "SELECT is_authorized FROM users WHERE user_id = ?", (user_id,)
        )
        row = await cursor.fetchone()
        return bool(row and row[0])


async def authorize_user(user_id: int) -> None:
    async with _connect() as db:
        await db.execute(
            "UPDATE users SET is_authorized = 1 WHERE user_id = ?", (user_id,)
        )
        await db.commit()


async def get_all_user_ids() -> list[int]:
    async with _connect() as db:
        cursor = await db.execute("SELECT user_id FROM users")
        return [row[0] for row in await cursor.fetchall()]


async def get_users_count() -> int:
    async with _connect() as db:
        cursor = await db.execute("SELECT COUNT(*) FROM users")
        row = await cursor.fetchone()
        return row[0] if row else 0


async def get_active_users_count() -> int:
    """Number of users who have sent at least one question."""
    async with _connect() as db:
        cursor = await db.execute(
            "SELECT COUNT(DISTINCT user_id) FROM questions"
        )
        row = await cursor.fetchone()
        return row[0] if row else 0


async def get_all_users() -> list[dict]:
    async with _connect() as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT user_id, username, full_name, is_authorized, joined_at "
            "FROM users ORDER BY joined_at"
        )
        return [dict(row) for row in await cursor.fetchall()]


async def get_user(user_id: int) -> dict | None:
    async with _connect() as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM users WHERE user_id = ?", (user_id,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def find_user_by_username(username: str) -> dict | None:
    username = username.lstrip("@").strip().lower()
    if not username:
        return None
    async with _connect() as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM users WHERE LOWER(username) = ?", (username,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def get_recent_users(limit: int = 20) -> list[dict]:
    async with _connect() as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM users ORDER BY joined_at DESC LIMIT ?", (limit,)
        )
        return [dict(row) for row in await cursor.fetchall()]


# Questions

async def create_question(
    user_id: int,
    username: str,
    full_name: str,
    text: str,
    is_anonymous: bool = False,
) -> int:
    async with _connect() as db:
        cursor = await db.execute(
            "INSERT INTO questions "
            "(user_id, username, full_name, question_text, is_anonymous, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, username, full_name, text, int(is_anonymous), time.time()),
        )
        await db.commit()
        return cursor.lastrowid


async def get_open_questions() -> list[dict]:
    async with _connect() as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM questions "
            "WHERE status IN ('open', 'in_progress') "
            "ORDER BY created_at ASC"
        )
        return [dict(row) for row in await cursor.fetchall()]


async def get_question(question_id: int) -> dict | None:
    async with _connect() as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM questions WHERE id = ?", (question_id,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def set_question_in_progress(question_id: int) -> None:
    async with _connect() as db:
        await db.execute(
            "UPDATE questions SET status = 'in_progress' WHERE id = ?",
            (question_id,),
        )
        await db.commit()


async def answer_question(question_id: int, answer_text: str) -> None:
    async with _connect() as db:
        await db.execute(
            "UPDATE questions "
            "SET answer_text = ?, status = 'answered', answered_at = ? "
            "WHERE id = ?",
            (answer_text, time.time(), question_id),
        )
        await db.commit()


async def get_user_questions(user_id: int) -> list[dict]:
    async with _connect() as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM questions WHERE user_id = ? "
            "ORDER BY created_at DESC LIMIT ?",
            (user_id, USER_QUESTIONS_LIMIT),
        )
        return [dict(row) for row in await cursor.fetchall()]


# Training signups
# Поле training_id в таблице на самом деле хранит group_id из каталога
# (одна запись = одна группа конкретного тренинга).

SIGNUP_OK = "ok"
SIGNUP_ALREADY = "already_signed_up"
SIGNUP_OTHER_GROUP = "signed_up_elsewhere"
SIGNUP_FULL = "full"


async def create_signup(
    group_id: str,
    user_id: int,
    username: str,
    full_name: str,
    is_admin: bool,
    same_training_group_ids: list[str],
    capacity: int,
) -> tuple[str, str | None]:
    """Создаёт запись с учётом бизнес-правил.

    Возвращает кортеж (status, payload):
      ("ok", None)                       — записан;
      ("already_signed_up", None)        — уже в этой группе (только для non-admin);
      ("signed_up_elsewhere", other_id)  — уже в другой группе того же тренинга;
      ("full", None)                     — в группе нет мест.

    Для админа всегда возвращает ("ok", None) и не проверяет capacity/duplicates —
    запись помечается флагом is_admin=1.
    """
    async with _connect() as db:
        if not is_admin and same_training_group_ids:
            placeholders = ",".join("?" for _ in same_training_group_ids)
            cursor = await db.execute(
                f"SELECT training_id FROM training_signups "
                f"WHERE user_id = ? AND is_admin = 0 "
                f"AND training_id IN ({placeholders}) LIMIT 1",
                (user_id, *same_training_group_ids),
            )
            existing = await cursor.fetchone()
            if existing:
                return (
                    (SIGNUP_ALREADY, None)
                    if existing[0] == group_id
                    else (SIGNUP_OTHER_GROUP, existing[0])
                )

            cursor = await db.execute(
                "SELECT COUNT(*) FROM training_signups "
                "WHERE training_id = ? AND is_admin = 0",
                (group_id,),
            )
            count = (await cursor.fetchone())[0]
            if count >= capacity:
                return (SIGNUP_FULL, None)

        await db.execute(
            "INSERT INTO training_signups "
            "(training_id, user_id, username, full_name, is_admin, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (group_id, user_id, username, full_name, int(is_admin), time.time()),
        )
        await db.commit()
        return (SIGNUP_OK, None)


async def delete_signup(group_id: str, user_id: int) -> int:
    """Удаляет все записи пользователя в группе. Возвращает число удалённых строк."""
    async with _connect() as db:
        cursor = await db.execute(
            "DELETE FROM training_signups WHERE training_id = ? AND user_id = ?",
            (group_id, user_id),
        )
        await db.commit()
        return cursor.rowcount


async def get_user_signups(user_id: int) -> list[dict]:
    async with _connect() as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM training_signups WHERE user_id = ? "
            "ORDER BY created_at DESC",
            (user_id,),
        )
        return [dict(row) for row in await cursor.fetchall()]


async def get_group_signups(group_id: str, include_admin: bool = True) -> list[dict]:
    async with _connect() as db:
        db.row_factory = aiosqlite.Row
        if include_admin:
            cursor = await db.execute(
                "SELECT * FROM training_signups WHERE training_id = ? "
                "ORDER BY created_at ASC",
                (group_id,),
            )
        else:
            cursor = await db.execute(
                "SELECT * FROM training_signups WHERE training_id = ? AND is_admin = 0 "
                "ORDER BY created_at ASC",
                (group_id,),
            )
        return [dict(row) for row in await cursor.fetchall()]


async def count_active_signups_for_groups(group_ids: list[str]) -> dict[str, int]:
    """Возвращает {group_id: count_of_non_admin_signups} для всех переданных групп."""
    result = {gid: 0 for gid in group_ids}
    if not group_ids:
        return result
    placeholders = ",".join("?" for _ in group_ids)
    async with _connect() as db:
        cursor = await db.execute(
            f"SELECT training_id, COUNT(*) FROM training_signups "
            f"WHERE training_id IN ({placeholders}) AND is_admin = 0 "
            f"GROUP BY training_id",
            group_ids,
        )
        for row in await cursor.fetchall():
            result[row[0]] = row[1]
        return result
