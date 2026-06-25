import csv
import io
import logging
from datetime import datetime

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

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
    get_all_signups,
    get_group_signups,
    get_user_signups,
    is_user_authorized,
)
from keyboards import (
    BTN_ADMIN_SIGNUPS,
    BTN_EXPORT_SIGNUPS,
    BTN_MY_SIGNUPS,
    BTN_TRAININGS,
    admin_keyboard,
    admin_signups_overview_kb,
    group_action_kb,
    groups_list_kb,
    trainings_list_kb,
    user_keyboard,
)
from trainings_catalog import (
    MSK,
    TRAININGS,
    active_trainings,
    format_group_text,
    format_group_when_short,
    format_training_full_text,
    get_group,
    get_training,
    time_until_label,
)

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

    text = f"<b>{training.title}</b>\n\n{format_training_full_text(training)}"
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

    await message.answer(
        texts.TRAININGS_PICKER_HEADER,
        reply_markup=trainings_list_kb(trainings),
    )


@router.callback_query(F.data == "tr_picker")
async def back_to_picker(callback: CallbackQuery) -> None:
    trainings = active_trainings()
    if not trainings:
        await _safe_edit(callback.message, texts.NO_TRAININGS)
        await callback.answer()
        return
    await _safe_edit(
        callback.message,
        texts.TRAININGS_PICKER_HEADER,
        reply_markup=trainings_list_kb(trainings),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("tr_view_"))
async def view_training(callback: CallbackQuery) -> None:
    training_id = callback.data.removeprefix("tr_view_")
    training = get_training(training_id)
    if not training:
        await callback.answer("Тренинг не найден", show_alert=True)
        return
    await _render_training(callback, callback.from_user.id, training, edit=True)


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
        format_group_text(group),
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
        text_parts.append(
            "⏰ Напоминания придут за сутки и за час до старта."
        )
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

    kb = group_action_kb(
        group_id,
        training.id,
        mode,
        other_group_id=other,
        is_admin=is_admin,
    )
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

    now = datetime.now(MSK)
    lines = []
    for s in signups:
        pair = get_group(s["training_id"])
        marker = " <i>(тест)</i>" if s["is_admin"] else ""
        if pair:
            t, g = pair
            block = [
                f"• {t.title}{marker}",
                f"  └ {g.title}",
                f"  {format_group_when_short(g)} — <i>{time_until_label(g.starts_at, now)}</i>",
            ]
            if g.meeting_url:
                block.append(f"  🔗 {g.meeting_url}")
        else:
            block = [
                f"• <i>группа «{s['training_id']}» (снята с публикации){marker}</i>"
            ]
        lines.append("\n".join(block))

    await message.answer(
        "📅 <b>Ваши записи на тренинги:</b>\n\n" + "\n\n".join(lines),
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


@router.message(Command("test_reminders"))
async def admin_test_reminders(message: Message) -> None:
    if not _is_admin(message.from_user.id):
        return
    from scheduler import REMINDER_1H, REMINDER_24H, build_reminder_preview

    await message.answer(
        "🧪 <b>Превью напоминаний для всех групп</b>\n"
        "<i>(только текст — реальные напоминания пойдут по расписанию)</i>"
    )
    for training in active_trainings():
        for group in training.groups:
            for kind, label in ((REMINDER_24H, "24h"), (REMINDER_1H, "1h")):
                preview = (
                    f"<i>↓ {label} · {group.title}</i>\n\n"
                    + build_reminder_preview(training, group, kind)
                )
                await message.answer(preview)


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

    write_kb = InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(
                text="✉️ Написать всем участникам",
                callback_data=f"grpcast_{group_id}",
            )
        ]]
    )

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
        reply_markup=write_kb if real else None,
    )
    await callback.answer()


# ---------- Admin: CSV export of signups ----------

def _build_signups_csv(rows: list[dict]) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=";")
    writer.writerow([
        "training_title",
        "training_id",
        "group_title",
        "group_id",
        "group_starts_at_msk",
        "user_id",
        "telegram_link",
        "username",
        "full_name",
        "is_admin_test",
        "signed_up_at",
    ])
    for s in rows:
        pair = get_group(s["training_id"])
        if pair:
            t, g = pair
            training_title = t.title
            training_id = t.id
            group_title = g.title
            group_starts = g.starts_at.strftime("%Y-%m-%d %H:%M MSK")
        else:
            training_title = ""
            training_id = ""
            group_title = "<снят с публикации>"
            group_starts = ""
        username = s.get("username") or ""
        link = (
            f"https://t.me/{username}"
            if username
            else f"tg://user?id={s['user_id']}"
        )
        signed_up = datetime.fromtimestamp(s["created_at"]).strftime("%Y-%m-%d %H:%M")
        writer.writerow([
            training_title,
            training_id,
            group_title,
            s["training_id"],  # это group_id
            group_starts,
            s["user_id"],
            link,
            f"@{username}" if username else "",
            s.get("full_name") or "",
            "да" if s.get("is_admin") else "нет",
            signed_up,
        ])
    return buf.getvalue().encode("utf-8-sig")


@router.message(F.text == BTN_EXPORT_SIGNUPS)
@router.message(Command("export_signups"))
async def admin_export_signups(message: Message) -> None:
    if not _is_admin(message.from_user.id):
        return

    signups = await get_all_signups()
    if not signups:
        await message.answer(
            "Записей пока нет — выгружать нечего.",
            reply_markup=admin_keyboard(),
        )
        return

    data = _build_signups_csv(signups)
    filename = f"signups_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
    real = sum(1 for s in signups if not s.get("is_admin"))
    test = len(signups) - real
    caption = (
        f"📥 Экспорт записей: <b>{len(signups)}</b> строк "
        f"({real} реальных + {test} тест-записей)."
    )
    await message.answer_document(
        BufferedInputFile(data, filename=filename),
        caption=caption,
        reply_markup=admin_keyboard(),
    )
