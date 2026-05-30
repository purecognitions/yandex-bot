"""Фоновая задача-планировщик напоминаний о старте групп.

Каждую минуту проверяет все активные группы и шлёт напоминания
участникам, которые записались (без админских тест-записей):
  • за 24 часа до starts_at
  • за 1 час до starts_at

Состояние «уже отправлено» хранится в таблице reminders_sent
(составной PK по group_id+reminder_type), так что двойной отправки
не будет даже после рестарта бота.

Если бот был выключен и плановое время прошло «давно» (больше grace-окна),
напоминание помечается как «отправлено» БЕЗ рассылки — чтобы не спамить
участников прошедших или давно стартовавших групп.
"""

import asyncio
import logging
from datetime import datetime, timedelta

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError

from database import get_group_signups, is_reminder_sent, mark_reminder_sent
from trainings_catalog import (
    MSK,
    TrainingGroup,
    Training,
    active_trainings,
    group_ends_at,
)

logger = logging.getLogger(__name__)


REMINDER_24H = "24h"
REMINDER_1H = "1h"

# Сколько времени после планового момента ещё имеет смысл слать напоминание.
# Дольше — помечаем как «отправлено» без рассылки.
GRACE_WINDOW = {
    REMINDER_24H: timedelta(hours=12),
    REMINDER_1H: timedelta(hours=1),
}

TICK_INTERVAL_SEC = 60
SEND_DELAY_SEC = 0.05


def _fmt_time(dt: datetime) -> str:
    return dt.strftime("%H:%M")


def _build_reminder_text(training: Training, group: TrainingGroup, kind: str) -> str:
    starts = group.starts_at
    ends = group_ends_at(group)

    if kind == REMINDER_24H:
        header = f"🔔 <b>Завтра в {_fmt_time(starts)} (МСК) — старт вашего тренинга!</b>"
        when_line = (
            f"📅 {starts.day}.{starts.month:02d} в "
            f"{_fmt_time(starts)}–{_fmt_time(ends)} МСК"
        )
    else:
        header = "🔔 <b>Через час — старт тренинга!</b>"
        when_line = f"📅 Сегодня в {_fmt_time(starts)}–{_fmt_time(ends)} МСК"

    parts = [
        header,
        "",
        f"<b>{training.title}</b>",
        f"<b>{group.title}</b>",
        "",
        when_line,
        f"👩‍🏫 Ведущая: {group.leader}",
    ]
    if group.meeting_url:
        parts.append("")
        parts.append(f"🔗 Ссылка на встречу: {group.meeting_url}")

    return "\n".join(parts)


async def _send_to_signups(
    bot: Bot,
    training: Training,
    group: TrainingGroup,
    kind: str,
) -> tuple[int, int]:
    text = _build_reminder_text(training, group, kind)
    signups = await get_group_signups(group.id, include_admin=False)
    sent = failed = 0
    for s in signups:
        try:
            await bot.send_message(s["user_id"], text)
            sent += 1
        except TelegramForbiddenError:
            failed += 1
        except Exception as exc:
            failed += 1
            logger.warning(
                "Reminder %s for %s failed for user %s: %s",
                kind, group.id, s["user_id"], exc,
            )
        await asyncio.sleep(SEND_DELAY_SEC)
    return sent, failed


async def _check_once(bot: Bot) -> None:
    now = datetime.now(MSK)
    for training in active_trainings():
        for group in training.groups:
            for kind, offset in (
                (REMINDER_24H, timedelta(hours=24)),
                (REMINDER_1H, timedelta(hours=1)),
            ):
                target = group.starts_at - offset
                if now < target:
                    continue
                if await is_reminder_sent(group.id, kind):
                    continue

                if now - target > GRACE_WINDOW[kind]:
                    logger.info(
                        "Skipping %s reminder for %s — past grace window "
                        "(target was %s, now %s)",
                        kind, group.id, target.isoformat(), now.isoformat(),
                    )
                    await mark_reminder_sent(group.id, kind)
                    continue

                sent, failed = await _send_to_signups(bot, training, group, kind)
                await mark_reminder_sent(group.id, kind)
                logger.info(
                    "Sent %s reminder for %s: delivered=%d, failed=%d",
                    kind, group.id, sent, failed,
                )


async def reminder_loop(bot: Bot) -> None:
    logger.info("Reminder scheduler started (MSK timezone)")
    while True:
        try:
            await _check_once(bot)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Reminder tick failed; will retry next minute")
        await asyncio.sleep(TICK_INTERVAL_SEC)


def build_reminder_preview(training: Training, group: TrainingGroup, kind: str) -> str:
    """Публичная обёртка для admin-команды /test_reminders."""
    return _build_reminder_text(training, group, kind)
