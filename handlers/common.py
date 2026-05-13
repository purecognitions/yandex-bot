from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

import texts
from config import ACCESS_CODE, ADMIN_IDS
from database import add_user, authorize_user, is_user_authorized
from keyboards import admin_keyboard, keyboard_for, user_keyboard
from states import AuthStates

router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    user = message.from_user
    await add_user(user.id, user.username or "", user.full_name or "")

    if user.id in ADMIN_IDS:
        await authorize_user(user.id)
        await message.answer(texts.ADMIN_WELCOME, reply_markup=admin_keyboard())
        return

    if await is_user_authorized(user.id):
        await message.answer(texts.USER_WELCOME_BACK, reply_markup=user_keyboard())
        return

    await state.set_state(AuthStates.waiting_for_code)
    await message.answer(texts.AUTH_PROMPT)


@router.message(AuthStates.waiting_for_code, F.text)
async def check_access_code(message: Message, state: FSMContext) -> None:
    if message.text.strip() == ACCESS_CODE:
        await authorize_user(message.from_user.id)
        await state.clear()
        await message.answer(texts.AUTH_SUCCESS, reply_markup=user_keyboard())
    else:
        await message.answer(texts.AUTH_FAIL)


@router.callback_query(F.data == "cancel")
async def on_cancel_callback(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.edit_text(texts.ACTION_CANCELLED)
    await callback.answer()


@router.message(Command("cancel"))
async def on_cancel_command(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(
        texts.ACTION_CANCELLED,
        reply_markup=keyboard_for(message.from_user.id),
    )
