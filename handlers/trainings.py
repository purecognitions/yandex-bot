import logging
from datetime import datetime

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

import texts
from config import ADMIN_IDS
from database import (
    count_signups_by_training,
    create_signup,
    delete_signup,
    get_training_signups,
    get_user_signups,
    is_user_authorized,
)
from keyboards import (
    BTN_ADMIN_SIGNUPS,
    BTN_MY_SIGNUPS,
    BTN_TRAININGS,
    admin_trainings_overview_kb,
    training_signup_kb,
    trainings_list_kb,
    user_keyboard,
)
from trainings_catalog import TRAININGS, active_trainings, get_training

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
            logger.warning("Failed to notify admin %s about training event: %s", admin_id, exc)


# ---------- User side ----------

@router.message(F.text == BTN_TRAININGS)
async def show_trainings(message: Message) -> None:
    if not await is_user_authorized(message.from_user.id):
        await message.answer(texts.AUTH_REQUIRED)
        return

    trainings = active_trainings()
    if not trainings:
        await message.answer(texts.NO_TRAININGS, reply_markup=user_keyboard())
        return

    await message.answer(texts.TRAININGS_HEADER, reply_markup=trainings_list_kb(trainings))


@router.callback_query(F.data == "tr_list")
async def back_to_list(callback: CallbackQuery) -> None:
    trainings = active_trainings()
    if not trainings:
        await callback.message.edit_text(texts.NO_TRAININGS)
        await callback.answer()
        return

    await callback.message.edit_text(
        texts.TRAININGS_HEADER,
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

    signups = await get_user_signups(callback.from_user.id)
    is_signed_up = any(s["training_id"] == training_id for s in signups)

    text = f"<b>{training.title}</b>\n\n{training.description}"
    if is_signed_up:
        text += "\n\n✅ <b>Вы уже записаны.</b>"

    await callback.message.edit_text(
        text,
        reply_markup=training_signup_kb(training_id, is_signed_up),
        disable_web_page_preview=True,
    )
    await callback.answer()


@router.callback_query(F.data.startswith("tr_signup_"))
async def signup_for_training(callback: CallbackQuery, bot: Bot) -> None:
    training_id = callback.data.removeprefix("tr_signup_")
    training = get_training(training_id)
    if not training:
        await callback.answer("Тренинг не найден", show_alert=True)
        return

    user = callback.from_user
    if not await is_user_authorized(user.id):
        await callback.answer("Сначала введите код доступа: /start", show_alert=True)
        return

    created = await create_signup(
        training_id=training_id,
        user_id=user.id,
        username=user.username or "",
        full_name=user.full_name or "",
    )
    if not created:
        await callback.answer("Вы уже записаны на этот тренинг.", show_alert=True)
        return

    await callback.message.edit_text(
        f"<b>{training.title}</b>\n\n"
        "✅ <b>Вы записаны!</b>\n\n"
        "Мы свяжемся с вами по поводу деталей.",
        reply_markup=training_signup_kb(training_id, True),
        disable_web_page_preview=True,
    )
    await callback.answer("Вы записаны!")

    await _notify_admins(
        bot,
        f"🎓 <b>Новая запись на тренинг</b>\n\n"
        f"Тренинг: <b>{training.title}</b>\n"
        f"Пользователь: {_display(user)}",
    )


@router.callback_query(F.data.startswith("tr_cancel_"))
async def cancel_signup(callback: CallbackQuery, bot: Bot) -> None:
    training_id = callback.data.removeprefix("tr_cancel_")
    training = get_training(training_id)
    if not training:
        await callback.answer("Тренинг не найден", show_alert=True)
        return

    user = callback.from_user
    removed = await delete_signup(training_id, user.id)
    if not removed:
        await callback.answer("Запись не найдена.", show_alert=True)
        return

    await callback.message.edit_text(
        f"<b>{training.title}</b>\n\n"
        "❌ <b>Запись отменена.</b>\n\n"
        f"{training.description}",
        reply_markup=training_signup_kb(training_id, False),
        disable_web_page_preview=True,
    )
    await callback.answer("Запись отменена")

    await _notify_admins(
        bot,
        f"🚫 <b>Отмена записи на тренинг</b>\n\n"
        f"Тренинг: <b>{training.title}</b>\n"
        f"Пользователь: {_display(user)}",
    )


@router.message(F.text == BTN_MY_SIGNUPS)
async def my_signups(message: Message) -> None:
    if not await is_user_authorized(message.from_user.id):
        await message.answer(texts.AUTH_REQUIRED)
        return

    signups = await get_user_signups(message.from_user.id)
    if not signups:
        await message.answer(texts.NO_USER_SIGNUPS, reply_markup=user_keyboard())
        return

    lines = []
    for s in signups:
        t = get_training(s["training_id"])
        title = t.title if t else f"<i>тренинг «{s['training_id']}» (снят с публикации)</i>"
        dt = datetime.fromtimestamp(s["created_at"]).strftime("%d.%m.%Y %H:%M")
        lines.append(f"• {title}\n  📅 записан: {dt}")

    await message.answer(
        "📅 <b>Ваши записи на тренинги:</b>\n\n" + "\n\n".join(lines),
        reply_markup=user_keyboard(),
    )


# ---------- Admin side ----------

@router.message(F.text == BTN_ADMIN_SIGNUPS)
@router.message(Command("signups"))
async def admin_show_overview(message: Message) -> None:
    if not _is_admin(message.from_user.id):
        return

    counts = await count_signups_by_training()
    total = sum(counts.values())

    lines = [f"🎓 <b>Записи на тренинги</b> (всего: {total})\n"]
    for t in TRAININGS:
        count = counts.get(t.id, 0)
        flag = "" if t.is_active else " <i>(скрыт)</i>"
        lines.append(f"• <b>{t.title}</b>{flag} — {count} чел.")

    # Считаем записи на удалённые из каталога тренинги
    catalog_ids = {t.id for t in TRAININGS}
    orphans = {tid: c for tid, c in counts.items() if tid not in catalog_ids}
    if orphans:
        lines.append("")
        lines.append("<i>Записи на снятые с публикации тренинги:</i>")
        for tid, c in orphans.items():
            lines.append(f"• <code>{tid}</code> — {c} чел.")

    await message.answer(
        "\n".join(lines),
        reply_markup=admin_trainings_overview_kb(TRAININGS),
    )


@router.callback_query(F.data.startswith("tr_admin_"))
async def admin_show_training_signups(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа", show_alert=True)
        return

    training_id = callback.data.removeprefix("tr_admin_")
    training = get_training(training_id)
    title = training.title if training else f"<code>{training_id}</code>"

    signups = await get_training_signups(training_id)
    if not signups:
        await callback.message.answer(f"<b>{title}</b>\n\nЗаписей пока нет.")
        await callback.answer()
        return

    lines = [f"<b>{title}</b>\n\n<b>Записи ({len(signups)}):</b>\n"]
    for i, s in enumerate(signups, 1):
        username = s.get("username") or ""
        full_name = s.get("full_name") or ""
        handle = f"@{username}" if username else (full_name or f"id {s['user_id']}")
        link = f"tg://user?id={s['user_id']}"
        dt = datetime.fromtimestamp(s["created_at"]).strftime("%d.%m %H:%M")
        lines.append(f"{i}. <a href=\"{link}\">{handle}</a> — {dt}")

    await callback.message.answer(
        "\n".join(lines),
        disable_web_page_preview=True,
    )
    await callback.answer()
