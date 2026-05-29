"""Каталог тренингов.

Чтобы добавить/изменить тренинг — отредактируйте список TRAININGS ниже
и сделайте `git pull && systemctl restart psy-bot` на сервере.

Поля:
  id          — короткий уникальный идентификатор (латиница/цифры/_), используется в callback_data.
                После того как на тренинг кто-то записался, НЕ меняйте id — иначе старые записи
                останутся, но без привязки к карточке.
  title       — то, что видно в кнопке и заголовке (с эмодзи)
  description — полное описание: длительность, ведущий, формат, для кого, цена и т.д.
                Поддерживается HTML (<b>, <i>, <a href="...">).
  is_active   — False = тренинг скрыт от пользователей (но видим админу в админ-разделе).
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Training:
    id: str
    title: str
    description: str
    is_active: bool = True


TRAININGS: list[Training] = [
    Training(
        id="example_1",
        title="🧘 Название тренинга 1",
        description=(
            "<i>Замените этот текст в trainings_catalog.py.</i>\n\n"
            "Здесь — полное описание тренинга: формат, длительность, "
            "ведущий, для кого подходит, что входит, как проходит."
        ),
    ),
    Training(
        id="example_2",
        title="💬 Название тренинга 2",
        description=(
            "<i>Замените этот текст в trainings_catalog.py.</i>\n\n"
            "Описание второго тренинга."
        ),
    ),
]


def get_training(training_id: str) -> Training | None:
    return next((t for t in TRAININGS if t.id == training_id), None)


def active_trainings() -> list[Training]:
    return [t for t in TRAININGS if t.is_active]
