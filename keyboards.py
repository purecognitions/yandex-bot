from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from config import ADMIN_IDS

BTN_ASK = "✉️ Задать вопрос специалисту"
BTN_MY_QUESTIONS = "📋 Мои вопросы"
BTN_TRAININGS = "🎓 Тренинги"
BTN_MY_SIGNUPS = "📅 Мои записи"
BTN_BROADCAST = "📢 Рассылка"
BTN_DM = "✉️ Написать пользователю"
BTN_INBOX = "📨 Входящие вопросы"
BTN_STATS = "📊 Статистика"
BTN_EXPORT = "📥 Экспорт логинов"
BTN_ADMIN_SIGNUPS = "🎓 Записи на тренинги"


def user_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_ASK)],
            [KeyboardButton(text=BTN_TRAININGS), KeyboardButton(text=BTN_MY_SIGNUPS)],
            [KeyboardButton(text=BTN_MY_QUESTIONS)],
        ],
        resize_keyboard=True,
    )


def admin_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_BROADCAST), KeyboardButton(text=BTN_DM)],
            [KeyboardButton(text=BTN_INBOX), KeyboardButton(text=BTN_ADMIN_SIGNUPS)],
            [KeyboardButton(text=BTN_STATS), KeyboardButton(text=BTN_EXPORT)],
        ],
        resize_keyboard=True,
    )


def cancel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")]
        ]
    )


def anonymity_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🙈 Анонимно", callback_data="anon_yes")],
            [InlineKeyboardButton(text="👤 С именем", callback_data="anon_no")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")],
        ]
    )


def broadcast_confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Отправить", callback_data="broadcast_confirm"),
                InlineKeyboardButton(text="❌ Отмена", callback_data="cancel"),
            ]
        ]
    )


def dm_confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Отправить", callback_data="dm_confirm"),
                InlineKeyboardButton(text="❌ Отмена", callback_data="cancel"),
            ]
        ]
    )


def dm_recipients_kb(users: list[dict]) -> InlineKeyboardMarkup:
    rows = []
    for u in users:
        label = (
            f"@{u['username']}"
            if u.get("username")
            else (u.get("full_name") or f"id {u['user_id']}")
        )[:48]
        rows.append([InlineKeyboardButton(text=label, callback_data=f"dm_pick_{u['user_id']}")])
    rows.append([InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def trainings_list_kb(trainings) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=t.title, callback_data=f"tr_view_{t.id}")]
        for t in trainings
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def training_signup_kb(training_id: str, is_signed_up: bool) -> InlineKeyboardMarkup:
    if is_signed_up:
        rows = [[InlineKeyboardButton(text="❌ Отменить запись", callback_data=f"tr_cancel_{training_id}")]]
    else:
        rows = [[InlineKeyboardButton(text="📝 Записаться", callback_data=f"tr_signup_{training_id}")]]
    rows.append([InlineKeyboardButton(text="⬅️ К списку", callback_data="tr_list")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_trainings_overview_kb(trainings) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=f"📋 {t.title}", callback_data=f"tr_admin_{t.id}")]
        for t in trainings
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def reply_kb(question_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✍️ Ответить", callback_data=f"reply_{question_id}")]
        ]
    )


def keyboard_for(user_id: int) -> ReplyKeyboardMarkup:
    return admin_keyboard() if user_id in ADMIN_IDS else user_keyboard()
