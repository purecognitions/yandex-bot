import logging
from datetime import datetime

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

import texts
from config import ADMIN_IDS
from database import (
    SIGNUP_ALREADY,
    SIGNUP_FULL,
    SIGNUP_OK,
    SIGNUP_OTHER_GROUP,
    count_active_signups_for_groups,
    create_signup,
    delete_signup,
    get_group_signups,
    get_user_signups,
    is_user_authorized,
)
from keyboards import (
    BTN_ADMIN_SIGNUPS,
    BTN_MY_SIGNUPS,
    BTN_TRAININGS,
    admin_signups_overview_kb,
    group_action_kb,
    groups_list_kb,
    user_keyboard,
)
from trainings_catalog import TRAININGS, active_trainings, get_group

logger = logging.getLogger(__name__)
router = Router()


def _is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def _display(user) -> str:
    if user.username:
        return f"@{user.username}"
    return user.full_name or f"id {user.id}"


async def _notify_admins(bot: Bot, text: str) -> None:
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text)
        except Exception as exc:
            logger.warning("Failed to notify admin %s: %s", admin_id, exc)


async def _safe_edit(message, text: str, reply_markup=None) -> None:
    """edit_text, игнорирующий 'message is not modified'."""
    try:
        await message.edit_text(
            text,
            reply_markup=reply_markup,
            disable_web_page_preview=True,
        )
    except TelegramBadRequest as exc:
        if "message is not modified" in str(exc).lower():
            return
        raise


def _user_signup_in_training(signups: list[dict], group_ids: list[str]) -> dict | None:
    """Найти non-admin запись пользователя в любой группе тренинга."""
    return next(
        (s for s in signups if s["training_id"] in group_ids and not s["is_admin"]),
        None,
    )


# ---------- User: training overview ----------

async def _render_training(target, user_id: int, training, *, edit: bool) -> None:
    """target: Message (для send) или CallbackQuery (для edit)."""
    group_ids = [g.id for g in training.groups]
    counts = await count_active_signups_for_groups(group_ids)
    signups = await get_user_signups(user_id)
    user_signup = _user_signup_in_training(signups, group_ids)
    user_group_id = user_signup["training_id"] if user_signup else None

    text = f"<b>{training.title}</b>\n\n{training.description}"
    if user_group_id:
        pair = get_group(user_group_id)
        if pair:
            _, ug = pair
            text += f"\n\n✅ Вы записаны в <b>{ug.title}</b>."

    kb = groups_list_kb(training, counts, user_group_id)
    if edit:
        await _safe_edit(target.message, text, reply_markup=kb)
        await target.answer()
    else:
        await target.answer(text, reply_markup=kb, disable_web_page_preview=True)


@router.message(F.text == BTN_TRAININGS)
async def show_trainings(message: Message) -> None:
    if not await is_user_authorized(message.from_user.id):
        await message.answer(texts.AUTH_REQUIRED)
        return

    trainings = active_trainings()
    if not trainings:
        await message.answer(texts.NO_TRAININGS, reply_markup=user_keyboard())
        return

    # Сейчас тренинг один — показываем его сразу.
    # Когда появятся несколько — заменить на список с выбором.
    await _render_training(message, message.from_user.id, trainings[0], edit=False)


@router.callback_query(F.data == "tr_back_to_training")
async def back_to_training(callback: CallbackQuery) -> None:
    trainings = active_trainings()
    if not trainings:
        await _safe_edit(callback.message, texts.NO_TRAININGS)
        await callback.answer()
        return
    await _render_training(callback, callback.from_user.id, trainings[0], edit=True)


# ---------- User: group view ----------

async def _render_group(callback: CallbackQuery, group_id: str) -> None:
    pair = get_group(group_id)
    if not pair:
        await callback.answer("Группа не найдена", show_alert=True)
        return
    training, group = pair

    user = callback.from_user
    is_admin = _is_admin(user.id)
    group_ids = [g.id for g in training.groups]
    counts = await count_active_signups_for_groups(group_ids)
    signups = await get_user_signups(user.id)

    count = counts.get(group_id, 0)
    seats_left = group.capacity - count

    text_parts = [
        f"<b>{group.title}</b>",
        "",
        group.schedule,
        group.leader,
        "",
        f"📊 Занято: <b>{count} / {group.capacity}</b>",
    ]

    # Определяем состояние и режим кнопок
    user_signup = _user_signup_in_training(signups, group_ids)
    admin_signups_here = [
        s for s in signups
        if s["training_id"] == group_id and s["is_admin"]
    ]

    if user_signup and user_signup["training_id"] == group_id:
        text_parts.append("")
        text_parts.append("✅ <b>Вы записаны в эту группу.</b>")
        mode, other = "cancel", None
    elif user_signup:
        other_pair = get_group(user_signup["training_id"])
        other_title = other_pair[1].title if other_pair else user_signup["training_id"]
        text_parts.append("")
        text_parts.append(
            f"⚠️ Вы уже записаны в <b>{other_title}</b>. "
            "Чтобы перейти, сначала отмените текущую запись."
        )
        mode, other = "blocked", user_signup["training_id"]
    elif seats_left <= 0 and not is_admin:
        text_parts.append("")
        text_parts.append("🚫 <b>Группа заполнена.</b> Выберите другую.")
        mode, other = "full", None
    else:
        mode, other = "signup", None

    if is_admin:
        if admin_signups_here:
            text_parts.append("")
            text_parts.append(
                f"🛠 <i>У вас {len(admin_signups_here)} тест-записей в этой группе. "
                "Можно отменить через кнопку (удалит все).</i>"
            )
            # для админа: показываем cancel если есть тест-записи, иначе signup-test
            mode = "cancel" if mode != "cancel" else mode
        else:
            text_parts.append("")
            text_parts.append(texts.ADMIN_TEST_HINT)
            mode = "signup"

    kb = group_action_kb(group_id, mode, other_group_id=other, is_admin=is_admin)
    await _safe_edit(callback.message, "\n".join(text_parts), reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.startswith("tr_group_"))
async def view_group(callback: CallbackQuery) -> None:
    await _render_group(callback, callback.data.removeprefix("tr_group_"))


# ---------- User: signup / cancel ----------

@router.callback_query(F.data.startswith("tr_signup_"))
async def signup_for_group(callback: CallbackQuery, bot: Bot) -> None:
    group_id = callback.data.removeprefix("tr_signup_")
    pair = get_group(group_id)
    if not pair:
        await callback.answer("Группа не найдена", show_alert=True)
        return
    training, group = pair

    user = callback.from_user
    if not await is_user_authorized(user.id):
        await callback.answer("Сначала введите код доступа: /start", show_alert=True)
        return

    is_admin = _is_admin(user.id)
    status, payload = await create_signup(
        group_id=group_id,
        user_id=user.id,
        username=user.username or "",
        full_name=user.full_name or "",
        is_admin=is_admin,
        same_training_group_ids=[g.id for g in training.groups],
        capacity=group.capacity,
    )

    if status == SIGNUP_ALREADY:
        await callback.answer("Вы уже записаны в эту группу.", show_alert=True)
        return
    if status == SIGNUP_OTHER_GROUP:
        other_pair = get_group(payload) if payload else None
        other_title = other_pair[1].title if other_pair else "другую группу"
        await callback.answer(
            f"Сначала отмените запись в {other_title}.",
            show_alert=True,
        )
        return
    if status == SIGNUP_FULL:
        await callback.answer("В этой группе закончились места.", show_alert=True)
        return

    # status == SIGNUP_OK
    await _render_group(callback, group_id)
    if not is_admin:
        await _notify_admins(
            bot,
            f"🎓 <b>Новая запись</b>\n\n"
            f"Тренинг: {training.title}\n"
            f"Группа: {group.title}\n"
            f"Пользователь: {_display(user)}",
        )


@router.callback_query(F.data.startswith("tr_cancel_"))
async def cancel_signup(callback: CallbackQuery, bot: Bot) -> None:
    group_id = callback.data.removeprefix("tr_cancel_")
    pair = get_group(group_id)
    if not pair:
        await callback.answer("Группа не найдена", show_alert=True)
        return
    training, group = pair

    user = callback.from_user
    removed = await delete_signup(group_id, user.id)
    if removed == 0:
        await callback.answer("Запись не найдена.", show_alert=True)
        return

    await _render_group(callback, group_id)
    if not _is_admin(user.id):
        await _notify_admins(
            bot,
            f"🚫 <b>Отмена записи</b>\n\n"
            f"Тренинг: {training.title}\n"
            f"Группа: {group.title}\n"
            f"Пользователь: {_display(user)}",
        )


# ---------- User: "Мои записи" ----------

@router.message(F.text == BTN_MY_SIGNUPS)
async def my_signups(message: Message) -> None:
    if not await is_user_authorized(message.from_user.id):
        await message.answer(texts.AUTH_REQUIRED)
        return

    signups = await get_user_signups(message.from_user.id)
    is_admin = _is_admin(message.from_user.id)
    if not is_admin:
        signups = [s for s in signups if not s["is_admin"]]

    if not signups:
        await message.answer(texts.NO_USER_SIGNUPS, reply_markup=user_keyboard())
        return

    lines = []
    for s in signups:
        pair = get_group(s["training_id"])
        if pair:
            t, g = pair
            title = f"{t.title}\n  └ {g.title}"
        else:
            title = f"<i>группа «{s['training_id']}» (снята с публикации)</i>"
        marker = " <i>(тест)</i>" if s["is_admin"] else ""
        dt = datetime.fromtimestamp(s["created_at"]).strftime("%d.%m %H:%M")
        lines.append(f"• {title}{marker}\n  📅 записан: {dt}")

    await message.answer(
        "📅 <b>Ваши записи:</b>\n\n" + "\n\n".join(lines),
        reply_markup=user_keyboard(),
    )


# ---------- Admin: overview & per-group list ----------

@router.message(F.text == BTN_ADMIN_SIGNUPS)
@router.message(Command("signups"))
async def admin_overview(message: Message) -> None:
    if not _is_admin(message.from_user.id):
        return

    all_group_ids = [g.id for t in TRAININGS for g in t.groups]
    counts_active = await count_active_signups_for_groups(all_group_ids)

    lines = ["🎓 <b>Записи на тренинги</b>\n"]
    for t in TRAININGS:
        flag = "" if t.is_active else " <i>(скрыт)</i>"
        lines.append(f"<b>{t.title}</b>{flag}")
        for g in t.groups:
            c = counts_active.get(g.id, 0)
            full = " 🚫 заполнено" if c >= g.capacity else ""
            lines.append(f"  • {g.title} — {c} / {g.capacity}{full}")
        lines.append("")

    await message.answer(
        "\n".join(lines).strip(),
        reply_markup=admin_signups_overview_kb(TRAININGS),
    )


@router.callback_query(F.data.startswith("tr_admin_"))
async def admin_show_group_signups(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа", show_alert=True)
        return

    group_id = callback.data.removeprefix("tr_admin_")
    pair = get_group(group_id)
    if pair:
        _, group = pair
        title = group.title
    else:
        title = f"<code>{group_id}</code> (снята с публикации)"

    signups = await get_group_signups(group_id, include_admin=True)
    real = [s for s in signups if not s["is_admin"]]
    test = [s for s in signups if s["is_admin"]]

    if not signups:
        await callback.message.answer(f"<b>{title}</b>\n\nЗаписей пока нет.")
        await callback.answer()
        return

    lines = [f"<b>{title}</b>\n"]
    if real:
        lines.append(f"<b>Участники ({len(real)}):</b>")
        for i, s in enumerate(real, 1):
            username = s.get("username") or ""
            full_name = s.get("full_name") or ""
            handle = f"@{username}" if username else (full_name or f"id {s['user_id']}")
            link = f"tg://user?id={s['user_id']}"
            dt = datetime.fromtimestamp(s["created_at"]).strftime("%d.%m %H:%M")
            lines.append(f"{i}. <a href=\"{link}\">{handle}</a> — {dt}")
    if test:
        lines.append("")
        lines.append(f"<i>🛠 Тест-записи админов ({len(test)}):</i>")
        for s in test:
            username = s.get("username") or ""
            full_name = s.get("full_name") or ""
            handle = f"@{username}" if username else (full_name or f"id {s['user_id']}")
            dt = datetime.fromtimestamp(s["created_at"]).strftime("%d.%m %H:%M")
            lines.append(f"  • {handle} — {dt}")

    await callback.message.answer(
        "\n".join(lines),
        disable_web_page_preview=True,
    )
    await callback.answer()
