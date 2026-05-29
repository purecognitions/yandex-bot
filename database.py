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
                created_at REAL,
                UNIQUE(training_id, user_id)
            );
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

async def create_signup(
    training_id: str,
    user_id: int,
    username: str,
    full_name: str,
) -> bool:
    """Возвращает True если запись создана, False если уже существовала."""
    async with _connect() as db:
        try:
            await db.execute(
                "INSERT INTO training_signups "
                "(training_id, user_id, username, full_name, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (training_id, user_id, username, full_name, time.time()),
            )
            await db.commit()
            return True
        except aiosqlite.IntegrityError:
            return False


async def delete_signup(training_id: str, user_id: int) -> bool:
    """Возвращает True если запись была и удалена, False если не было."""
    async with _connect() as db:
        cursor = await db.execute(
            "DELETE FROM training_signups WHERE training_id = ? AND user_id = ?",
            (training_id, user_id),
        )
        await db.commit()
        return cursor.rowcount > 0


async def get_user_signups(user_id: int) -> list[dict]:
    async with _connect() as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM training_signups WHERE user_id = ? "
            "ORDER BY created_at DESC",
            (user_id,),
        )
        return [dict(row) for row in await cursor.fetchall()]


async def get_training_signups(training_id: str) -> list[dict]:
    async with _connect() as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM training_signups WHERE training_id = ? "
            "ORDER BY created_at ASC",
            (training_id,),
        )
        return [dict(row) for row in await cursor.fetchall()]


async def count_signups_by_training() -> dict[str, int]:
    async with _connect() as db:
        cursor = await db.execute(
            "SELECT training_id, COUNT(*) FROM training_signups GROUP BY training_id"
        )
        return {row[0]: row[1] for row in await cursor.fetchall()}
