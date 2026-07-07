import logging
from datetime import datetime

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

import texts
from config import ADMIN_IDS
from database import create_question, get_user_questions, is_user_authorized
from keyboards import (
    BTN_ASK,
    BTN_MATERIALS,
    BTN_MY_QUESTIONS,
    anonymity_kb,
    keyboard_for,
    reply_kb,
    user_keyboard,
)
from states import AskStates

logger = logging.getLogger(__name__)
router = Router()

STATUS_ICONS = {"open": "⏳", "in_progress": "🔄", "answered": "✅"}
PREVIEW_QUESTION = 80
PREVIEW_ANSWER = 120


def _display_name(username: str, full_name: str, is_anonymous: bool) -> str:
    if is_anonymous:
        return "Аноним"
    return f"@{username}" if username else full_name


def _truncate(text: str, limit: int) -> str:
    return text[:limit] + ("…" if len(text) > limit else "")


@router.message(F.text == BTN_ASK)
async def ask_start(message: Message, state: FSMContext) -> None:
    if not await is_user_authorized(message.from_user.id):
        await message.answer(texts.AUTH_REQUIRED)
        return

    await state.set_state(AskStates.choosing_anonymity)
    await message.answer(texts.ASK_ANONYMITY, reply_markup=anonymity_kb())


@router.callback_query(F.data.in_({"anon_yes", "anon_no"}), AskStates.choosing_anonymity)
async def ask_anonymity_chosen(callback: CallbackQuery, state: FSMContext) -> None:
    is_anonymous = callback.data == "anon_yes"
    await state.update_data(is_anonymous=is_anonymous)
    await state.set_state(AskStates.waiting_for_question)

    mode = "анонимно 🙈" if is_anonymous else "с именем 👤"
    await callback.message.edit_text(
        f"✉️ <b>Задайте ваш вопрос</b> ({mode})\n\n"
        "Напишите всё, что вас беспокоит — специалист ответит "
        "в течение рабочего дня.\n\n"
        "/cancel — отмена"
    )
    await callback.answer()


@router.message(AskStates.waiting_for_question, F.text)
async def ask_save(message: Message, state: FSMContext, bot: Bot) -> None:
    user = message.from_user
    data = await state.get_data()
    is_anonymous = bool(data.get("is_anonymous"))

    question_id = await create_question(
        user_id=user.id,
        username=user.username or "",
        full_name=user.full_name or "",
        text=message.text,
        is_anonymous=is_anonymous,
    )
    await state.clear()

    await message.answer(
        f"✅ Ваш вопрос <b>#{question_id}</b> отправлен специалисту!\n"
        "Ответ придёт в этот чат.",
        reply_markup=user_keyboard(),
    )

    display_name = _display_name(user.username or "", user.full_name or "", is_anonymous)
    notify_text = (
        f"📩 <b>Новый вопрос #{question_id}</b>\n"
        f"От: {display_name}\n\n<i>{message.text}</i>"
    )

    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, notify_text, reply_markup=reply_kb(question_id))
        except Exception as exc:
            logger.warning("Failed to notify admin %s: %s", admin_id, exc)


@router.message(F.text == BTN_MATERIALS)
async def materials(message: Message) -> None:
    if not await is_user_authorized(message.from_user.id):
        await message.answer(texts.AUTH_REQUIRED)
        return

    await message.answer(
        texts.MATERIALS,
        reply_markup=keyboard_for(message.from_user.id),
        disable_web_page_preview=True,
    )


@router.message(F.text == BTN_MY_QUESTIONS)
async def my_questions(message: Message) -> None:
    questions = await get_user_questions(message.from_user.id)
    if not questions:
        await message.answer(texts.NO_QUESTIONS, reply_markup=user_keyboard())
        return

    lines = []
    for q in questions:
        icon = STATUS_ICONS.get(q["status"], "⏳")
        dt = datetime.fromtimestamp(q["created_at"]).strftime("%d.%m.%Y %H:%M")
        line = (
            f"{icon} <b>#{q['id']}</b> ({dt})\n"
            f"<i>{_truncate(q['question_text'], PREVIEW_QUESTION)}</i>"
        )
        if q["status"] == "in_progress":
            line += "\n🔄 <b>Специалист готовит ответ…</b>"
        if q["answer_text"]:
            line += f"\n💬 <b>Ответ:</b> {_truncate(q['answer_text'], PREVIEW_ANSWER)}"
        lines.append(line)

    await message.answer(
        "📋 <b>Ваши вопросы</b> (последние 10):\n\n" + "\n\n".join(lines),
        reply_markup=user_keyboard(),
    )
