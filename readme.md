# Telegram Global Lead Searcher

Поиск сообщений по ключевым словам во **всём Telegram** (глобальный поиск) + опциональная фильтрация «тёплых» лидов через модель OpenAI (ChatGPT и аналоги).

Скрипт ищет посты/сообщения по вашим ключевым словам → сохраняет сырые результаты → (при желании) пропускает их через ИИ для выделения потенциальных заказов, заявок, вопросов «где купить», «ищу специалиста» и т.п.

Подходит для мониторинга фриланс-запросов, крипто-объявлений, поиска услуг, упоминаний брендов и т.д.

**Примеры запросов:**
- «нужен битрикс», «заказ битрикс24»
- «ищу python разработчика удалённо»
- «продам USDT», «куплю TON»
- «крипта airdrop», «free nft»

## Возможности

- Глобальный поиск по ключевым словам (не ограничен чатами/каналами)
- Фильтр по дате начала поиска (`--since`)
- Лимит сообщений на каждое ключевое слово
- Сохранение сырых сообщений в промежуточный JSON
- Опциональная фильтрация через OpenAI (батчами)
- Человеческий вывод или чистый JSON
- Построчное логирование каждого запуска в `log/log_ГГГГ-ММ-ДД.jsonl`
- Полная обработка ошибок с записью traceback в лог

## Требования

- Python 3.8 – 3.12 (рекомендуется 3.10+)
- Библиотеки: `telethon`, `openai`, `pyyaml`

## Получение данных для Telegram API

1. Зарегистрируйте приложение на https://my.telegram.org/apps
2. Скопируйте `api_id` (число) и `api_hash` (строка)
3. При первом запуске скрипт попросит ввести:
   - api_id
   - api_hash
   - номер телефона (+7999...)
4. Данные сохраняются в `cred.yaml`

**Важно**: не коммитьте `cred.yaml` в git!

## Установка

```bash
# Клонируем репозиторий (замените на свой URL)
git clone https://github.com/ВАШ_ЛОГИН/tg-lead-searcher.git
cd tg-lead-searcher

# Виртуальное окружение
python -m venv venv

# Активация
# Windows (cmd)
venv\Scripts\activate

# Windows (PowerShell)
.\venv\Scripts\Activate.ps1

# Linux/macOS
source venv/bin/activate

# Установка зависимостей
pip install -r requirements.txt
# или вручную:
# pip install telethon openai pyyaml
Примеры запуска
Bash# Простой поиск (50 сообщений на слово)
python tg_search.py "битрикс, bitrix24, 1с-битрикс"

# Больше сообщений + дата
python tg_search.py "python django flask" -l 120 --since 2026-01-01

# Только JSON-вывод (удобно для пайплайнов)
python tg_search.py "крипта TON USDT" -j -l 80

# С ИИ-фильтром лидов (батч 15)
python tg_search.py "нужен разработчик, ищу фрилансера" -a 15 -o leads.json

# Всё вместе + свои файлы
python tg_search.py "удалёнка python" -l 100 -a 20 -o leads_2026-02.json -i raw_2026-02.json --since 2026-02-01

# Справка
python tg_search.py --help
Аргументы командной строки
textkeywords_str          Ключевые слова через запятую (обязательно)

-l, --limit N         Макс. сообщений на каждое слово       (по умолчанию: 50)
-o, --output FILE     Файл с финальным результатом          (по умолчанию: tg_result.json)
-i, --intermediate FILE  Промежуточный файл с сырыми сообщениями (по умолчанию: tg_raw_messages.json)
-j, --json-only       Только чистый JSON в stdout
--since YYYY-MM-DD    Искать сообщения начиная с этой даты
-a, --ai N            Включить ИИ-фильтр лидов, батч размером N (0 = выключено)
Структура проекта
texttg-lead-searcher/
├── tg_search.py          ← основной скрипт (или main.py)
├── lead.py               ← логика OpenAI-фильтрации (можно использовать тот же, что и в VK-скрипте)
├── cred.yaml             ← api_id, api_hash, phone (не коммитить!)
├── prompt.txt            ← шаблон промпта для ИИ (создаётся при первом использовании -a)
├── gpt_cred.yaml         ← OpenAI api_key + model
├── requirements.txt
├── log/                  ← создаётся автоматически
│   └── log_2026-02-25.jsonl   ← построчный лог запусков
└── README.md
```

## Логи
Каждый запуск записывается одной строкой в файл log/log_ГГГГ-ММ-ДД.jsonl (JSON Lines).
Пример записи:
JSON{
  "timestamp": "2026-02-25T14:12:45.678Z",
  "end_time": "2026-02-25T14:13:18.901Z",
  "duration_seconds": 33.22,
  "keywords": ["нужен битрикс", "bitrix24"],
  "params": {
    "limit_per_keyword": 60,
    "since": "2026-01-01",
    "ai_filter": true,
    "batch_size_ai": 15
  },
  "num_raw_messages": 47,
  "num_leads_after_ai": 8,
  "error": null
}
Если произошла ошибка — в поле "error" будет сообщение и traceback.
Удобные команды:
```Bash
# Последние 10 запусков
tail -n 10 log/log_$(date +%Y-%m-%d).jsonl

# Только успешные (без ошибок)
jq 'select(.error == null)' log/log_2026-02-25.jsonl