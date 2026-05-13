import asyncio
import logging
from datetime import datetime

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

import texts
from config import ADMIN_IDS, BROADCAST_DELAY
from database import (
    answer_question,
    get_all_user_ids,
    get_open_questions,
    get_question,
    get_users_count,
    set_question_in_progress,
)
from keyboards import (
    BTN_BROADCAST,
    BTN_INBOX,
    BTN_STATS,
    admin_keyboard,
    broadcast_confirm_kb,
    cancel_kb,
    reply_kb,
)
from states import AnswerStates, BroadcastStates

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
    await state.update_data(
        text=message.text or message.caption,
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


async def _send_broadcast_message(bot: Bot, uid: int, data: dict) -> None:
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
            await _send_broadcast_message(bot, uid, data)
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
async def stats(message: Message) -> None:
    if not _is_admin(message.from_user.id):
        return
    count = await get_users_count()
    open_q = await get_open_questions()
    await message.answer(
        f"📊 <b>Статистика</b>\n\n"
        f"👥 Пользователей: <b>{count}</b>\n"
        f"📩 Неотвеченных вопросов: <b>{len(open_q)}</b>",
        reply_markup=admin_keyboard(),
    )
