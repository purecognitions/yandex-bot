# Yandex Bot — Telegram-бот психологической поддержки

Telegram-бот, через который сотрудники компании могут задать вопрос
специалисту-психологу (по желанию — анонимно), а специалист отвечает
из админ-панели в том же боте. Поддерживается рассылка сообщений по
всем пользователям и базовая статистика.

## Возможности

- Авторизация пользователей по корпоративному коду доступа
- Отправка вопросов специалисту (анонимно или с именем)
- История своих обращений со статусами `⏳ открыт / 🔄 в работе / ✅ отвечен`
- Админ-панель: входящие вопросы, ответ в один клик, рассылка (текст,
  фото, видео, документ), статистика

## Стек

- Python 3.10+
- [aiogram 3](https://docs.aiogram.dev/) — Telegram Bot framework
- [aiosqlite](https://github.com/omnilib/aiosqlite) — асинхронный SQLite
- [python-dotenv](https://github.com/theskumar/python-dotenv) — чтение `.env`

## Структура проекта

```
.
├── bot.py              # точка входа
├── config.py           # переменные окружения и их валидация
├── database.py         # слой работы с SQLite
├── keyboards.py        # клавиатуры и подписи кнопок
├── states.py           # FSM-состояния
├── texts.py            # тексты сообщений
└── handlers/
    ├── __init__.py     # сборка общего роутера
    ├── common.py       # /start, авторизация, /cancel
    ├── user.py         # пользователь: задать вопрос, мои вопросы
    └── admin.py        # админ: рассылка, входящие, ответ, статистика
```

## Установка

```bash
git clone https://github.com/lefotsifemm-design/yandex-bot.git
cd yandex-bot
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
```

## Настройка

Скопируйте `.env.example` в `.env` и заполните:

```env
BOT_TOKEN=123456:ABC-DEF...
ACCESS_CODE=secret123
ADMIN_IDS=11111111,22222222
```

| Переменная             | Назначение                                                |
| ---------------------- | --------------------------------------------------------- |
| `BOT_TOKEN`            | Токен бота от [@BotFather](https://t.me/BotFather)        |
| `ACCESS_CODE`          | Код, который сотрудники вводят на `/start`                |
| `ADMIN_IDS`            | Список Telegram-ID специалистов через запятую             |
| `DB_PATH`              | Путь до SQLite-файла (по умолчанию `bot_database.db`)     |
| `BROADCAST_DELAY`      | Пауза между сообщениями рассылки, секунды (по умолчанию `0.05`) |
| `USER_QUESTIONS_LIMIT` | Сколько последних вопросов показывать пользователю (`10`) |

## Запуск

```bash
python bot.py
```

При первом запуске будут созданы таблицы `users` и `questions` в SQLite.

## Лицензия

MIT
