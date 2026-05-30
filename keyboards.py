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
BTN_EXPORT_SIGNUPS = "📥 Экспорт записей"
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
            [KeyboardButton(text=BTN_STATS)],
            [KeyboardButton(text=BTN_EXPORT), KeyboardButton(text=BTN_EXPORT_SIGNUPS)],
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
    """Список тренингов на верхнем уровне (шаг 1)."""
    rows = [
        [InlineKeyboardButton(text=t.title, callback_data=f"tr_view_{t.id}")]
        for t in trainings
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def groups_list_kb(training, counts: dict, user_group_id: str | None) -> InlineKeyboardMarkup:
    """Список групп тренинга со счётчиками мест + кнопка возврата к списку тренингов."""
    rows = []
    for g in training.groups:
        c = counts.get(g.id, 0)
        if c >= g.capacity:
            seats = "🚫 нет мест"
        else:
            seats = f"{g.capacity - c} мест свободно"
        marker = " ✅" if user_group_id == g.id else ""
        label = f"{g.title} · {seats}{marker}"
        rows.append([InlineKeyboardButton(text=label[:64], callback_data=f"tr_group_{g.id}")])
    rows.append([InlineKeyboardButton(text="⬅️ К списку тренингов", callback_data="tr_picker")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def group_action_kb(
    group_id: str,
    training_id: str,
    mode: str,
    other_group_id: str | None = None,
    is_admin: bool = False,
) -> InlineKeyboardMarkup:
    """mode: 'signup' | 'cancel' | 'blocked' | 'full'"""
    rows = []
    if mode == "signup":
        text = "📝 Записаться (тест)" if is_admin else "📝 Записаться"
        rows.append([InlineKeyboardButton(text=text, callback_data=f"tr_signup_{group_id}")])
    elif mode == "cancel":
        rows.append([InlineKeyboardButton(text="❌ Отменить запись", callback_data=f"tr_cancel_{group_id}")])
    elif mode == "blocked" and other_group_id:
        rows.append([InlineKeyboardButton(
            text="↩️ Перейти к моей группе",
            callback_data=f"tr_group_{other_group_id}",
        )])
    # для "full" дополнительных action-кнопок нет
    rows.append([InlineKeyboardButton(text="⬅️ К группам", callback_data=f"tr_view_{training_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_signups_overview_kb(trainings) -> InlineKeyboardMarkup:
    rows = []
    for t in trainings:
        for g in t.groups:
            rows.append([InlineKeyboardButton(
                text=f"📋 {g.title} — список",
                callback_data=f"tr_admin_{g.id}",
            )])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def reply_kb(question_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✍️ Ответить", callback_data=f"reply_{question_id}")]
        ]
    )


def keyboard_for(user_id: int) -> ReplyKeyboardMarkup:
    return admin_keyboard() if user_id in ADMIN_IDS else user_keyboard()
