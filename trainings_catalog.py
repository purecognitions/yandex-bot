"""Каталог тренингов и групп.

Структура: каждый тренинг (Training) содержит несколько групп (TrainingGroup).
Каждая группа описывается одной точкой данных — `starts_at` (datetime в МСК).
Всё остальное (день недели, расписание, дата последней встречи, текст для
карточки тренинга) — генерируется автоматически.

Чтобы добавить/поменять — отредактируйте TRAININGS ниже и сделайте на сервере
`git pull && systemctl restart psy-bot`.

⚠️ ВАЖНО про id:
  • id группы (TrainingGroup.id) хранится в БД и в таблице напоминаний.
  • Если переименуете id уже опубликованной группы — записи и состояние
    напоминаний «осиротеют». Заводите новый id вместо переименования.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


# МСК — фиксированный сдвиг +3, без перехода на летнее время (так с 2011 года).
MSK = timezone(timedelta(hours=3), name="MSK")


# ---------- Локализация ----------

_WEEKDAY_NOM = {
    0: "понедельник", 1: "вторник", 2: "среда",
    3: "четверг", 4: "пятница", 5: "суббота", 6: "воскресенье",
}
_EVERY_WEEKDAY = {
    0: "каждый понедельник", 1: "каждый вторник", 2: "каждую среду",
    3: "каждый четверг", 4: "каждую пятницу", 5: "каждую субботу",
    6: "каждое воскресенье",
}
_MONTH_GEN = {
    1: "января", 2: "февраля", 3: "марта", 4: "апреля",
    5: "мая", 6: "июня", 7: "июля", 8: "августа",
    9: "сентября", 10: "октября", 11: "ноября", 12: "декабря",
}
_GROUP_COUNT_WORD = {2: "двух", 3: "трёх", 4: "четырёх", 5: "пяти", 6: "шести"}


def _plural_meetings(n: int) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return "встреча"
    if 2 <= n % 10 <= 4 and not (12 <= n % 100 <= 14):
        return "встречи"
    return "встреч"


def _groups_choice_phrase(n: int) -> str:
    if n == 1:
        return "в одну группу"
    word = _GROUP_COUNT_WORD.get(n, str(n))
    return f"в любую из {word} групп"


def _format_date(dt: datetime) -> str:
    """3 июня"""
    return f"{dt.day} {_MONTH_GEN[dt.month]}"


def _format_time(dt: datetime) -> str:
    return dt.strftime("%H:%M")


def _plural(n: int, one: str, few: str, many: str) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not (12 <= n % 100 <= 14):
        return few
    return many


def time_until_label(starts_at: datetime, now: datetime) -> str:
    """'через 3 дня', 'через 5 часов', 'через 12 минут', 'уже началось'."""
    delta = starts_at - now
    total_sec = int(delta.total_seconds())
    if total_sec <= 0:
        # Тренинг идёт или уже закончился
        return "уже идёт или прошёл"
    days = total_sec // 86400
    if days >= 1:
        return f"через {days} {_plural(days, 'день', 'дня', 'дней')}"
    hours = total_sec // 3600
    if hours >= 1:
        return f"через {hours} {_plural(hours, 'час', 'часа', 'часов')}"
    minutes = max(total_sec // 60, 1)
    return f"через {minutes} {_plural(minutes, 'минуту', 'минуты', 'минут')}"


def format_group_when_short(g) -> str:
    """Короткое 'Старт: 3 июня (среда) в 15:00 МСК' — для списка записей."""
    weekday = _WEEKDAY_NOM[g.starts_at.weekday()]
    return (
        f"Старт: {_format_date(g.starts_at)} ({weekday}) "
        f"в {_format_time(g.starts_at)} МСК"
    )


# ---------- Модель ----------

@dataclass(frozen=True)
class TrainingGroup:
    id: str               # глобально уникальный slug
    title: str            # "1️⃣ Группа 1"
    starts_at: datetime   # с tz МСК — момент первой встречи
    leader: str           # "Аня Бондаренко" (без эмодзи — добавим при рендере)
    duration_minutes: int = 120
    total_meetings: int = 6
    capacity: int = 15
    meeting_url: str = ""  # ссылка на Zoom/Meet — попадает в напоминания


@dataclass(frozen=True)
class Training:
    id: str
    title: str
    description: str      # только intro (без списка групп — он генерируется автоматом)
    groups: list[TrainingGroup]
    is_active: bool = True


# ---------- Производные вычисления ----------

def group_ends_at(g: TrainingGroup) -> datetime:
    return g.starts_at + timedelta(minutes=g.duration_minutes)


def group_last_meeting(g: TrainingGroup) -> datetime:
    return g.starts_at + timedelta(weeks=g.total_meetings - 1)


# ---------- Рендеринг текста ----------

def format_group_text(g: TrainingGroup) -> str:
    """Полный блок информации о группе в стиле анонса."""
    starts = g.starts_at
    ends = group_ends_at(g)
    last = group_last_meeting(g)
    weekday = _WEEKDAY_NOM[starts.weekday()]
    every = _EVERY_WEEKDAY[starts.weekday()]
    return (
        f"<b>{g.title}</b>\n"
        f"Старт: {_format_date(starts)}, {weekday}, "
        f"с {_format_time(starts)} до {_format_time(ends)}\n"
        f"Как проходит: встречаемся онлайн {every} "
        f"с {_format_time(starts)} до {_format_time(ends)}, "
        f"всего {g.total_meetings} {_plural_meetings(g.total_meetings)}\n"
        f"Последняя встреча группы: {_format_date(last)}\n"
        f"Ведущая: {g.leader}"
    )


def format_training_full_text(t: Training) -> str:
    """Intro + автогенерированный список групп. Title добавляется в хендлере."""
    blocks = [t.description.rstrip()]
    if t.groups:
        blocks.append(
            f"<b>Вы можете записаться {_groups_choice_phrase(len(t.groups))}:</b>"
        )
        for g in t.groups:
            blocks.append(format_group_text(g))
    return "\n\n".join(blocks)


# ---------- Помощники навигации ----------

def active_trainings() -> list[Training]:
    return [t for t in TRAININGS if t.is_active]


def get_training(training_id: str) -> Training | None:
    return next((t for t in TRAININGS if t.id == training_id), None)


def get_group(group_id: str) -> tuple[Training, TrainingGroup] | None:
    for t in TRAININGS:
        for g in t.groups:
            if g.id == group_id:
                return (t, g)
    return None


# ---------- Каталог ----------

TRAININGS: list[Training] = [
    Training(
        id="emotional_resilience",
        title="🧠 Тренинг навыков эмоциональной устойчивости",
        description=(
            "Задача тренинга — помочь лучше понимать, как устроен стресс, "
            "как он влияет на мышление, эмоции и тело, и главное — как можно "
            "научиться этим состоянием управлять.\n\n"
            "<b>Внутри программы мы будем работать с несколькими направлениями:</b>\n"
            "— управление вниманием и развитие осознанности — чтобы раньше "
            "замечать перегрузку и не уходить в автоматические стрессовые реакции\n"
            "— работа с мышлением: как распознавать ловушки мышления и не "
            "раскручивать стресс дальше\n"
            "— телесная регуляция: дыхательные и другие техники, которые "
            "помогают напрямую влиять на состояние нервной системы\n\n"
            "По итогам тренинга у вас сформируется системный набор базовых "
            "навыков эмоциональной устойчивости: как быстрее восстанавливаться, "
            "как не доводить себя до перегрева и как поддерживать устойчивость "
            "в условиях высокой нагрузки."
        ),
        groups=[
            TrainingGroup(
                id="er_g1",
                title="1️⃣ Группа 1",
                starts_at=datetime(2026, 6, 3, 15, 0, tzinfo=MSK),
                leader="Аня Бондаренко",
            ),
            TrainingGroup(
                id="er_g2",
                title="2️⃣ Группа 2",
                starts_at=datetime(2026, 6, 9, 15, 0, tzinfo=MSK),
                leader="Алёна Шарикова",
            ),
            TrainingGroup(
                id="er_g3",
                title="3️⃣ Группа 3",
                starts_at=datetime(2026, 7, 22, 15, 0, tzinfo=MSK),
                leader="Женя Янке",
            ),
        ],
    ),
]
