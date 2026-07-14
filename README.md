# AI Sales Agent — личный Telegram-бот

Поиск потенциальных бизнес-клиентов (OpenStreetMap Overpass API), AI-анализ через Claude,
генерация сообщений для холодного контакта, CRM-лайт со статусами и напоминаниями.

## Запуск

Требуется **Python 3.11+**. Запускать бот нужно **строго из venv на 3.11**, а не
из глобального `python` (см. предупреждение ниже — из-за этого уже был реальный
краш несовместимости версий).

```bat
:: 1. venv именно на 3.11 (системный python может быть 3.10 — не подойдёт)
py -3.11 -m venv venv
venv\Scripts\activate

:: 2. Зависимости (в активированный venv) — из ПОЛНОГО lock-файла:
pip install -r requirements-lock.txt
:: requirements-lock.txt пинит всё дерево (в т.ч. транзитивные httpx, pydantic и
:: т.п.) — воспроизводимая установка без риска подтянуть несовместимую версию.
:: requirements.txt — только верхнеуровневые пакеты, для чтения/обновления версий.

:: 3. Конфиг
copy .env.example .env
:: впиши в .env:
::   BOT_TOKEN=...          (от @BotFather)
::   LLM_PROVIDER=openrouter (бесплатно) или anthropic
::   LLM_API_KEY=...         (ключ выбранного провайдера)
::   LLM_MODEL=moonshotai/kimi-k2.6:free   (для openrouter; без лишнего префикса LLM_MODEL=)
:: чтобы вернуться на Anthropic: LLM_PROVIDER=anthropic + ANTHROPIC_API_KEY

:: 4. Старт (таблицы SQLite создадутся автоматически)
python bot.py
```

Linux/macOS: `python3.11 -m venv venv && source venv/bin/activate` вместо первых двух строк.

### Основной способ запуска — `run.bat` / `run.sh`

После разовой установки (шаги 1–3 выше) бот запускается лаунчером — руками
активировать venv и печатать `python bot.py` каждый раз не нужно:

- **Windows:** дважды кликни **`run.bat`** (или запусти из консоли). Он сам
  перейдёт в папку проекта, активирует venv и стартует бота. Если venv ещё нет —
  покажет понятную ошибку (`[ERROR] venv не найден…`), а не голый traceback.
- **Linux/macOS:** `./run.sh` (при первом запуске один раз: `chmod +x run.sh`).

Остановка — **`Ctrl+C`**: бот завершится штатно с сообщением
`[INFO] … Бот остановлен пользователем (Ctrl+C).` и кодом выхода 0, без пугающего
трейсбека.

> ⚠️ **Запускай только через активированный venv.** Если вызвать `python bot.py`
> без активации (`venv\Scripts\activate`), Python возьмёт **глобальные `--user`
> пакеты**, версии которых могут не совпадать с протестированными в
> `requirements.txt`. Именно так возник краш `AsyncClient.__init__() got an
> unexpected keyword argument 'proxies'`: в проде стоял старый `openai`, не
> совместимый со свежим `httpx`. При старте `bot.py` логирует warning, если
> интерпретатор не 3.11+ или похоже, что запуск идёт не из venv, — но это
> подстраховка, а не замена активации.

### Живая проверка LLM (не мок)

```bat
python scripts\smoke_llm.py
```

Делает один реальный вызов к настроенному в `.env` провайдеру (анализ + генерация)
и печатает сырой ответ модели. Удобно, чтобы отделить проблему конфига/сети/версий
пакетов от логики бота.

### Живой прогон всех функций (не мок)

```bat
python scripts\live_walkthrough.py
```

Прогоняет весь пользовательский путь (старт → меню → поиск → карточка →
AI-анализ → генерация → CRM → напоминания) прямыми вызовами реальных хендлеров,
но **без мокания** Overpass и LLM — реальная сеть. Пишет во временную БД, не
трогая `sales_agent.db`. Ловит баги, которые не видны на моках (напр. города,
где OSM хранит имя в другом регистре/языке). Не часть pytest.

## Тесты

```bash
pytest --cov
```

Тесты не ходят в сеть: Overpass и оба LLM-клиента (Anthropic и OpenAI-совместимый)
замоканы, БД — in-memory SQLite.

## Chat Lead Monitor

Отдельный пассивный источник лидов из открытых Telegram-чатов: Telethon слушает
новые сообщения, проверяет только чаты из настроек, прогоняет их через
keyword-фильтр и LLM-score для nail-ниши, затем сохраняет релевантные сообщения
в общую CRM. Список участников чатов не запрашивается.

Настройка в `.env` без правки кода:

```env
CHAT_MONITOR_OWNER_TG_ID=123456789
CHAT_MONITOR_API_ID=123456
CHAT_MONITOR_API_HASH=your_api_hash
CHAT_MONITOR_PHONE=+77001234567
CHAT_MONITOR_SESSION_PATH=chat_monitor.session
CHAT_MONITOR_FORCE_SMS=false
CHAT_MONITOR_CHATS=@open_nails_chat,-1001234567890
CHAT_MONITOR_MIN_SCORE=0.7
```

`CHAT_MONITOR_CHATS` и `CHAT_MONITOR_MIN_SCORE` используются как начальные
значения. Дальше управлять ими можно прямо в боте: главное меню ->
`Chat Monitor` -> `Добавить чат` / `Изменить threshold` / `Включить мониторинг`.

Секреты Telethon (`API_ID`, `API_HASH`, `PHONE`, `SESSION_PATH`) намеренно
остаются только в `.env` и не вводятся в Telegram-чат боту. Ключевые слова
nail-фильтра расширяются в `chat_monitor/keywords_nail.py`.

Запуск монитора отдельным процессом из корня проекта:

```bat
python -m chat_monitor.runner
```

При первом запуске Telethon попросит код. Он обычно приходит в официальный
Telegram-клиент на этом номере, а не SMS. Проверь активные устройства, архивные
чаты и `Service Notifications`. Если код не приходит, поставь
`CHAT_MONITOR_FORCE_SMS=true`, подожди несколько минут и запусти runner заново.
После успешного ввода кода будет создан `*.session` файл; он чувствительный и
игнорируется через `.gitignore`.

Если код всё равно не приходит, используй QR-логин без SMS:

```bat
python scripts\telethon_qr_login.py
```

Скрипт создаст и откроет `chat_monitor_qr.png`. Сканируй его из Telegram:
`Settings -> Devices -> Link Desktop Device`. После успешного скана будет
авторизован тот же `CHAT_MONITOR_SESSION_PATH`, и `chat_monitor.runner` запустится
без кода.

## Структура

- `bot.py` — точка входа (polling + фоновый поллер напоминаний)
- `config.py` — настройки из `.env` (pydantic-settings)
- `db/` — модели (User, Lead, Reminder) и CRUD
- `services/` — Overpass-клиент, LLM-провайдер (Anthropic/OpenAI-совместимый: анализ + генерация), поллер напоминаний
- `chat_monitor/` — Telethon-монитор открытых чатов, keyword-фильтр и сохранение chat-лидов в CRM
- `handlers/` — aiogram-роутеры: старт, меню, поиск, анализ, сообщения, CRM
- `keyboards/`, `states/` — inline-клавиатуры и FSM-состояния
- `utils/` — кастомные эмодзи (`emoji_config.py`) и безопасная отправка (`safe_send.py`)
- `tests/` — pytest (166 тестов)

## Кастомные премиум-эмодзи

Тексты сообщений используют кастомные эмодзи из пака
[tgmacicons](https://t.me/addemoji/tgmacicons) через HTML-тег
`<tg-emoji emoji-id="...">X</tg-emoji>` (требуется `parse_mode="HTML"` — включён
глобально в `bot.py`).

- `utils/emoji_config.py` — маппинг Unicode → emoji-id, класс `E` (HTML для текстов)
  и класс `P` (обычный юникод для `show_alert`, где HTML не рендерится).
- ID получены через @userinfobot. Несколько эмодзи осознанно делят один ID
  (алиасы одного визуала: 📞/☎️/📱, 📅/🗓 и т.п.) — см. комментарий в файле.
- **В кнопках (`InlineKeyboardButton`) кастомные эмодзи не используются** —
  Telegram не рендерит `<tg-emoji>` в тексте кнопок.

**Если эмодзи перестали отображаться** (пак удалён/ID невалиден): все отправки идут
через `utils/safe_send.py` (`safe_answer` / `safe_edit` / `safe_bot_send`) — при
`TelegramBadRequest` (например `EMOJI_INVALID`) сообщение автоматически
переотправляется с обычными юникод-эмодзи. Пользователь без ответа не останется.
Чтобы обновить ID: добавь пак заново, отправь эмодзи боту @userinfobot и впиши
новые ID в `CUSTOM_EMOJIS`.

## Заметки

- Время напоминаний — UTC.
- Лимит результатов поиска — 60 (MAX_LIMIT), иначе Overpass может вернуть тысячи строк.
- Соцсети (`socials`) почти всегда пусты — OSM их практически не отдаёт.
- Версии в `requirements.txt` — верхнеуровневые пакеты; полный lock всего дерева
  (включая транзитивные) — в `requirements-lock.txt`, ставить прод из него.
  Регенерация после смены версий: `pip install -r requirements.txt && pip freeze
  > requirements-lock.txt` в чистом venv. `pip check` — без конфликтов.
