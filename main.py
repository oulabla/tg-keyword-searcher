import asyncio
import re
import sys
import json
import argparse
from datetime import datetime, UTC
from pathlib import Path
from telethon import TelegramClient
from telethon.tl.functions.messages import SearchGlobalRequest
from telethon.tl.types import InputMessagesFilterEmpty, InputPeerEmpty
import yaml
from getpass import getpass

# ────────────────────────────────────────────────
# ВАШИ ДАННЫЕ
# ────────────────────────────────────────────────
SESSION_NAME = 'global_search_session'
CRED_FILE    = "cred.yaml"
DEFAULT_JSON = "result.json"


def load_or_create_credentials(json_only=False):
    cred_path = Path(CRED_FILE)

    if cred_path.is_file() and cred_path.stat().st_size > 0:
        try:
            with open(cred_path, encoding="utf-8") as f:
                data = yaml.safe_load(f)

            required = {"api_id", "api_hash", "phone"}
            if not isinstance(data, dict) or not required.issubset(data.keys()):
                print("В файле cred.yaml отсутствуют некоторые обязательные поля.")
                return ask_and_save_credentials()

            data["api_id"] = int(data["api_id"])
            if not json_only:
                print("Успешно загружены данные из cred.yaml")
            return data

        except Exception as e:
            print(f"Ошибка чтения {CRED_FILE}: {e}")
            return ask_and_save_credentials()

    return ask_and_save_credentials()


def ask_and_save_credentials():
    print("\nНеобходимо ввести данные для Telegram API\n")
    api_id  = input("api_id  (число)         : ").strip()
    api_hash = input("api_hash (строка)       : ").strip()
    phone   = input("Номер телефона (+7999...) : ").strip()

    try:
        api_id = int(api_id)
    except ValueError:
        print("api_id должен быть числом!")
        sys.exit(1)

    credentials = {"api_id": api_id, "api_hash": api_hash, "phone": phone}

    with open(CRED_FILE, "w", encoding="utf-8") as f:
        yaml.safe_dump(credentials, f, allow_unicode=True, sort_keys=False)

    print(f"\nДанные сохранены в {CRED_FILE}\n")
    return credentials


async def global_search(client, keywords, limit_per_keyword=50, min_date=None, json_only=False):
    all_results = []

    for keyword in keywords:
        if not json_only:
            print(f"Поиск по: {keyword!r}", file=sys.stderr)

        offset_rate = 0
        offset_peer = InputPeerEmpty()
        offset_id   = 0
        collected   = 0

        while collected < limit_per_keyword:
            try:
                result = await client(SearchGlobalRequest(
                    q           = keyword,
                    filter      = InputMessagesFilterEmpty(),
                    min_date    = min_date,
                    max_date    = None,
                    offset_rate = offset_rate,
                    offset_peer = offset_peer,
                    offset_id   = offset_id,
                    limit       = min(60, limit_per_keyword - collected)
                ))

                if not result.messages:
                    print(f"  → больше нет результатов", file=sys.stderr)
                    break

                for message in result.messages:
                    if not message.message:
                        continue

                    try:
                        chat   = await message.get_chat()
                        sender = await message.get_sender()
                    except Exception as e:
                        print(f"  Пропуск (chat/sender error): {e}", file=sys.stderr)
                        continue

                    chat_title = (
                        getattr(chat, 'title', None) or
                        getattr(chat, 'username', None) or
                        f"ID {getattr(chat, 'id', '???')}"
                    ).strip() or "Без названия"

                    sender_name = (
                        f"{sender.first_name or ''} {sender.last_name or ''}".strip()
                        if sender and hasattr(sender, 'first_name') else
                        f"Скрытый/удалённый (ID {message.sender_id or '?'})"
                    )

                    link = None
                    if message.chat_id and message.chat_id < 0:
                        clean_id = str(message.chat_id)[4:] if str(message.chat_id).startswith('-100') else str(abs(message.chat_id))
                        link = f"https://t.me/c/{clean_id}/{message.id}"

                    all_results.append({
                        'keyword'    : keyword,
                        'chat_id'    : message.chat_id,
                        'chat_title' : chat_title,
                        'message_id' : message.id,
                        'date'       : message.date.isoformat(),
                        'text'       : message.message,
                        'sender_id'  : message.sender_id,
                        'sender_name': sender_name,
                        'link'       : link
                    })

                    collected += 1
                    if collected >= limit_per_keyword:
                        break

                if not result.messages:
                    break

                last_msg = result.messages[-1]
                offset_id   = last_msg.id
                offset_peer = last_msg.peer_id

                if not json_only:
                    print(f"  Собрано {collected}/{limit_per_keyword}", file=sys.stderr)

                await asyncio.sleep(3.5)

            except Exception as e:
                err = str(e)
                print(f"  Ошибка: {err}", file=sys.stderr)

                if "FLOOD_WAIT" in err:
                    wait = 60
                    m = re.search(r'\b(\d+)\b', err)
                    if m:
                        wait = int(m.group(1))
                    print(f"  FLOOD_WAIT → ждём ~{wait + 10} сек...", file=sys.stderr)
                    await asyncio.sleep(wait + 10)
                elif any(x in err for x in ["PEER_ID_INVALID", "Cannot cast"]):
                    break
                else:
                    await asyncio.sleep(5)

    return all_results


def parse_arguments():
    parser = argparse.ArgumentParser(
        description="Глобальный поиск в Telegram по ключевым словам",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog="""
Примеры:
  python %(prog)s "битрикс, 1С, bitrix" -l 30 -o bitrix.json
  python %(prog)s "python django flask" --json-only
  python %(prog)s "крипта, BTC" -j -l 100
        """
    )

    # Позиционный аргумент — ключевые слова (обязательный)
    parser.add_argument(
        'keywords_str',
        type=str,
        help="Ключевые слова через запятую в кавычках (первый аргумент)"
    )

    # Остальные опциональные
    parser.add_argument('-l', '--limit', type=int, default=50,
                        help="Макс. количество сообщений на одно слово (по умолчанию 50)")
    parser.add_argument('-o', '--output', type=str, default=DEFAULT_JSON,
                        help=f"Имя выходного JSON-файла (по умолчанию: {DEFAULT_JSON})")
    parser.add_argument('-j', '--json-only', action='store_true',
                        help="Выводить в консоль только JSON и ничего больше")
    parser.add_argument('--since', type=str, default=None,
                        help="Дата в формате YYYY-MM-DD, начиная с которой искать")

    return parser.parse_args()

async def main():
    args = parse_arguments()

    # ─── Парсим ключевые слова из строки ───────────────────────────────
    raw_keywords = args.keywords_str.strip()
    if not raw_keywords:
        print("Ошибка: нужно указать хотя бы одно ключевое слово", file=sys.stderr)
        sys.exit(1)

    # Разбиваем по запятой и чистим
    keywords = [kw.strip() for kw in raw_keywords.split(',') if kw.strip()]

    if not keywords:
        print("Ошибка: после разбора не осталось ни одного ключевого слова", file=sys.stderr)
        sys.exit(1)

    # Лимит
    limit_per_kw = max(1, args.limit)

    # Дата
    min_date = None
    if args.since:
        try:
            min_date = datetime.strptime(args.since, "%Y-%m-%d")
        except ValueError:
            print(f"Неверный формат даты: {args.since!r}. Ожидается YYYY-MM-DD", file=sys.stderr)
            sys.exit(1)

    creds = load_or_create_credentials(args.json_only)

    client = TelegramClient(SESSION_NAME, creds['api_id'], creds['api_hash'])

    if not args.json_only:
        print("Запуск клиента...", file=sys.stderr)

    await client.start(phone=creds['phone'])

    if not args.json_only:
        print(f"Авторизация успешна\nКлючевые слова: {', '.join(keywords)!r}\n", file=sys.stderr)

    results = await global_search(client, keywords, limit_per_keyword=limit_per_kw, min_date=min_date, json_only=args.json_only)

    # Сортируем от новых к старым
    results.sort(key=lambda x: x['date'], reverse=True)

    output_data = {
        "metadata": {
            "keywords": keywords,
            "limit_per_keyword": limit_per_kw,
            "total_found": len(results),
            "since": min_date.isoformat() if min_date else None,
            "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z")
        },
        "results": results
    }

    json_str = json.dumps(output_data, ensure_ascii=False, indent=2)

    if args.json_only:
        print(json_str)
        return

    # Обычный вывод
    print(f"\nНайдено сообщений: {len(results)}\n", file=sys.stderr)

    for i, r in enumerate(results, 1):
        date_str = r['date'][:19].replace("T", " ")
        preview = r['text'].replace('\n', ' ').strip()

        print(f"#{i:03d}  {date_str}  [{r['chat_title']}]  {r['sender_name']}")
        print(f"   {preview}")
        if r['link']:
            print(f"   → {r['link']}")
        print("─" * 70)

    # Сохранение
    try:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(json_str)
        print(f"\nРезультат сохранён → {args.output}", file=sys.stderr)
    except Exception as e:
        print(f"Ошибка сохранения: {e}", file=sys.stderr)


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nОстановлено пользователем", file=sys.stderr)
    except Exception as e:
        print(f"Критическая ошибка: {e}", file=sys.stderr)
        sys.exit(1)