import asyncio
import csv
import io
import logging
import re
from datetime import datetime

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramForbiddenError
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, Message

import texts
from config import ADMIN_IDS, BROADCAST_DELAY
from database import (
    answer_question,
    find_user_by_username,
    get_active_users_count,
    get_all_user_ids,
    get_all_users,
    get_open_questions,
    get_question,
    get_recent_users,
    get_user,
    get_users_count,
    set_question_in_progress,
)
from keyboards import (
    BTN_BROADCAST,
    BTN_DM,
    BTN_EXPORT,
    BTN_INBOX,
    BTN_STATS,
    admin_keyboard,
    broadcast_confirm_kb,
    cancel_kb,
    dm_confirm_kb,
    dm_recipients_kb,
    reply_kb,
)
from states import AnswerStates, BroadcastStates, DirectMessageStates

logger = logging.getLogger(__name__)
router = Router()


def _is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def _display_name(username: str, full_name: str, is_anonymous: bool) -> str:
    if is_anonymous:
        return "Аноним"
    return f"@{username}" if username else full_name


# Broadcast

@router.message(F.text == BTN_BROADCAST)
@router.message(Command("broadcast"))
async def broadcast_start(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        await message.answer(texts.ACCESS_DENIED)
        return

    await state.set_state(BroadcastStates.waiting_for_content)
    await message.answer(texts.BROADCAST_START, reply_markup=cancel_kb())


@router.message(BroadcastStates.waiting_for_content)
async def broadcast_preview(message: Message, state: FSMContext) -> None:
    raw_text = message.html_text or message.caption
    clean_text = _strip_custom_emoji(raw_text) if raw_text else None
    await state.update_data(
        text=clean_text,
        photo_id=message.photo[-1].file_id if message.photo else None,
        video_id=message.video.file_id if message.video else None,
        document_id=message.document.file_id if message.document else None,
    )

    count = await get_users_count()
    await state.set_state(BroadcastStates.confirm)
    await message.answer(
        f"👆 Вот ваше сообщение. Отправить его <b>{count}</b> пользователям?",
        reply_markup=broadcast_confirm_kb(),
    )


def _strip_custom_emoji(html: str) -> str:
    """Replace <tg-emoji ...>fallback</tg-emoji> with plain fallback character."""
    return re.sub(r"<tg-emoji[^>]*>([^<]*)</tg-emoji>", r"\1", html)


async def _send_message_payload(bot: Bot, uid: int, data: dict) -> None:
    text = data.get("text")
    if data.get("photo_id"):
        await bot.send_photo(uid, data["photo_id"], caption=text)
    elif data.get("video_id"):
        await bot.send_video(uid, data["video_id"], caption=text)
    elif data.get("document_id"):
        await bot.send_document(uid, data["document_id"], caption=text)
    else:
        await bot.send_message(uid, text or "")


@router.callback_query(F.data == "broadcast_confirm", BroadcastStates.confirm)
async def broadcast_execute(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    data = await state.get_data()
    await state.clear()
    await callback.message.edit_text(texts.BROADCAST_RUNNING)

    success = failed = 0
    for uid in await get_all_user_ids():
        try:
            await _send_message_payload(bot, uid, data)
            success += 1
        except Exception as exc:
            failed += 1
            logger.warning("Broadcast delivery failed for %s: %s", uid, exc)
        await asyncio.sleep(BROADCAST_DELAY)

    await callback.message.answer(
        f"✅ Рассылка завершена!\n\n"
        f"• Доставлено: <b>{success}</b>\n"
        f"• Не доставлено: <b>{failed}</b>",
        reply_markup=admin_keyboard(),
    )


# Direct message to one user

def _format_user(u: dict) -> str:
    handle = f"@{u['username']}" if u.get("username") else (u.get("full_name") or "—")
    return f"{handle} (id {u['user_id']})"


async def _resolve_recipient(query: str) -> dict | None:
    query = query.strip()
    if not query:
        return None
    if query.lstrip("-").isdigit():
        return await get_user(int(query))
    return await find_user_by_username(query)


@router.message(F.text == BTN_DM)
@router.message(Command("dm"))
async def dm_start(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        await message.answer(texts.ACCESS_DENIED)
        return

    recent = await get_recent_users(20)
    await state.set_state(DirectMessageStates.waiting_for_recipient)
    await message.answer(texts.DM_START, reply_markup=dm_recipients_kb(recent))


@router.callback_query(F.data.startswith("dm_pick_"), DirectMessageStates.waiting_for_recipient)
async def dm_pick_from_list(callback: CallbackQuery, state: FSMContext) -> None:
    user_id = int(callback.data.split("_", 2)[2])
    recipient = await get_user(user_id)
    if not recipient:
        await callback.answer("Пользователь не найден", show_alert=True)
        return

    label = _format_user(recipient)
    await state.update_data(recipient_id=recipient["user_id"], recipient_label=label)
    await state.set_state(DirectMessageStates.waiting_for_content)
    await callback.message.edit_text(
        f"👤 Получатель: <b>{label}</b>\n\n{texts.DM_ASK_CONTENT}"
    )
    await callback.answer()


@router.message(DirectMessageStates.waiting_for_recipient, F.text)
async def dm_recipient_by_text(message: Message, state: FSMContext) -> None:
    recipient = await _resolve_recipient(message.text)
    if not recipient:
        await message.answer(texts.DM_RECIPIENT_NOT_FOUND)
        return

    label = _format_user(recipient)
    await state.update_data(recipient_id=recipient["user_id"], recipient_label=label)
    await state.set_state(DirectMessageStates.waiting_for_content)
    await message.answer(
        f"👤 Получатель: <b>{label}</b>\n\n{texts.DM_ASK_CONTENT}",
        reply_markup=cancel_kb(),
    )


@router.message(DirectMessageStates.waiting_for_content)
async def dm_preview(message: Message, state: FSMContext) -> None:
    if not (message.text or message.caption or message.photo or message.video or message.document):
        await message.answer(texts.DM_UNSUPPORTED_CONTENT)
        return

    raw_text = message.html_text or message.caption
    clean_text = _strip_custom_emoji(raw_text) if raw_text else None
    await state.update_data(
        text=clean_text,
        photo_id=message.photo[-1].file_id if message.photo else None,
        video_id=message.video.file_id if message.video else None,
        document_id=message.document.file_id if message.document else None,
    )

    data = await state.get_data()
    await state.set_state(DirectMessageStates.confirm)
    await message.answer(
        f"👆 Отправить это сообщение пользователю <b>{data['recipient_label']}</b>?",
        reply_markup=dm_confirm_kb(),
    )


@router.callback_query(F.data == "dm_confirm", DirectMessageStates.confirm)
async def dm_send(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    data = await state.get_data()
    await state.clear()
    uid = data["recipient_id"]
    label = data["recipient_label"]

    try:
        await _send_message_payload(bot, uid, data)
    except TelegramForbiddenError:
        await callback.message.edit_text(texts.DM_BLOCKED.format(label=f"<b>{label}</b>"))
        await callback.message.answer("Готов к следующему действию.", reply_markup=admin_keyboard())
        await callback.answer()
        return
    except Exception as exc:
        logger.exception("DM send failed to %s", uid)
        await callback.message.edit_text(
            f"⚠️ Ошибка при отправке пользователю <b>{label}</b>:\n<code>{exc}</code>"
        )
        await callback.message.answer("Готов к следующему действию.", reply_markup=admin_keyboard())
        await callback.answer()
        return

    await callback.message.edit_text(f"✅ Сообщение отправлено пользователю <b>{label}</b>.")
    await callback.message.answer("Готов к следующему действию.", reply_markup=admin_keyboard())
    await callback.answer()


# Inbox & answers

@router.message(F.text == BTN_INBOX)
async def admin_open_questions(message: Message) -> None:
    if not _is_admin(message.from_user.id):
        return

    questions = await get_open_questions()
    if not questions:
        await message.answer(texts.NO_OPEN_QUESTIONS, reply_markup=admin_keyboard())
        return

    for q in questions:
        dt = datetime.fromtimestamp(q["created_at"]).strftime("%d.%m.%Y %H:%M")
        display_name = _display_name(
            q.get("username") or "",
            q.get("full_name") or "",
            bool(q.get("is_anonymous")),
        )
        status_label = " 🔄" if q["status"] == "in_progress" else ""
        await message.answer(
            f"📩 <b>Вопрос #{q['id']}</b>{status_label} — {dt}\n"
            f"От: {display_name}\n\n<i>{q['question_text']}</i>",
            reply_markup=reply_kb(q["id"]),
        )


@router.callback_query(F.data.startswith("reply_"))
async def reply_to_question(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа", show_alert=True)
        return

    question_id = int(callback.data.split("_", 1)[1])
    question = await get_question(question_id)

    if not question:
        await callback.answer("Вопрос не найден", show_alert=True)
        return
    if question["status"] == "answered":
        await callback.answer("На этот вопрос уже ответили", show_alert=True)
        return

    if question["status"] == "open":
        await set_question_in_progress(question_id)
        try:
            await bot.send_message(
                question["user_id"],
                f"🔄 Специалист взял ваш вопрос <b>#{question_id}</b> в работу. "
                "Ожидайте ответ!",
            )
        except Exception as exc:
            logger.warning("Failed to notify user about in_progress: %s", exc)

    await state.set_state(AnswerStates.waiting_for_answer)
    await state.update_data(question_id=question_id)

    await callback.message.answer(
        f"✍️ Напишите ответ на <b>вопрос #{question_id}</b>:\n\n"
        f"<i>{question['question_text']}</i>\n\n/cancel — отмена",
        reply_markup=cancel_kb(),
    )
    await callback.answer()


@router.message(AnswerStates.waiting_for_answer, F.text)
async def save_answer(message: Message, state: FSMContext, bot: Bot) -> None:
    data = await state.get_data()
    question_id = data["question_id"]
    question = await get_question(question_id)

    if not question:
        await state.clear()
        await message.answer("Вопрос не найден.", reply_markup=admin_keyboard())
        return

    await answer_question(question_id, message.text)
    await state.clear()

    await message.answer(
        f"✅ Ответ на вопрос <b>#{question_id}</b> сохранён и отправлен пользователю.",
        reply_markup=admin_keyboard(),
    )

    try:
        await bot.send_message(
            question["user_id"],
            f"💬 <b>Ответ специалиста</b> на ваш вопрос <b>#{question_id}</b>:\n\n"
            f"<i>Вы спрашивали:</i>\n{question['question_text']}\n\n"
            f"<b>Ответ:</b>\n{message.text}",
        )
    except Exception as exc:
        logger.warning("Failed to deliver answer to user: %s", exc)
        await message.answer(texts.ANSWER_DELIVERY_FAILED)


# Stats

@router.message(F.text == BTN_STATS)
@router.message(Command("stats"))
async def stats(message: Message) -> None:
    if not _is_admin(message.from_user.id):
        return

    total = await get_users_count()
    active = await get_active_users_count()
    silent = max(total - active, 0)
    open_q = await get_open_questions()

    await message.answer(
        "📊 <b>Статистика</b>\n\n"
        f"👥 Всего пользователей: <b>{total}</b>\n"
        f"✍️ Написали в бот: <b>{active}</b>\n"
        f"🤐 Не написали ни разу: <b>{silent}</b>\n"
        f"📩 Неотвеченных вопросов: <b>{len(open_q)}</b>",
        reply_markup=admin_keyboard(),
    )


# Export

def _build_users_csv(users: list[dict]) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";")
    writer.writerow(
        ["user_id", "username", "telegram_link", "full_name", "authorized", "joined_at"]
    )
    for u in users:
        username = u["username"] or ""
        link = (
            f"https://t.me/{username}"
            if username
            else f"tg://user?id={u['user_id']}"
        )
        joined = (
            datetime.fromtimestamp(u["joined_at"]).strftime("%Y-%m-%d %H:%M")
            if u["joined_at"]
            else ""
        )
        writer.writerow(
            [
                u["user_id"],
                f"@{username}" if username else "",
                link,
                u["full_name"] or "",
                "да" if u["is_authorized"] else "нет",
                joined,
            ]
        )
    # utf-8-sig — чтобы Excel корректно открыл кириллицу
    return buffer.getvalue().encode("utf-8-sig")


@router.message(F.text == BTN_EXPORT)
@router.message(Command("export"))
async def export_users(message: Message) -> None:
    if not _is_admin(message.from_user.id):
        await message.answer(texts.ACCESS_DENIED)
        return

    users = await get_all_users()
    if not users:
        await message.answer(
            "В базе пока нет пользователей.", reply_markup=admin_keyboard()
        )
        return

    data = _build_users_csv(users)
    filename = f"participants_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
    await message.answer_document(
        BufferedInputFile(data, filename=filename),
        caption=f"📥 Экспорт участников: <b>{len(users)}</b> чел.",
        reply_markup=admin_keyboard(),
    )
