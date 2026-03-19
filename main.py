import asyncio
import re
import sys
import json
import argparse
import traceback
from datetime import datetime, UTC
from pathlib import Path
from telethon import TelegramClient
from telethon.tl.functions.messages import SearchGlobalRequest
from telethon.tl.types import InputMessagesFilterEmpty, InputPeerEmpty
import yaml
from openai import OpenAI
import lead  # ← ваш модуль lead.py
import uuid
import requests

# ────────────────────────────────────────────────
SESSION_NAME = 'global_search_session'
CRED_FILE    = "cred.yaml"
CLIENT_ID_FILE = "client_id.txt"
NETLOG_URL   = "http://185.233.187.55:8080/v1/netlog/create"
APP_NAME     = "tg-global-leads-parser"          # ← желательно поменять на своё

DEFAULT_RESULT = "result.json"
DEFAULT_INTERMEDIATE = "tg_result.json"
LOG_DIR      = Path("log")

# ────────────────────────────────────────────────

def get_or_create_client_id():
    path = Path(CLIENT_ID_FILE)
    if path.is_file():
        try:
            cid = path.read_text(encoding="utf-8").strip()
            if cid and len(cid) > 20:
                return cid
        except:
            pass

    new_id = str(uuid.uuid4())
    try:
        path.write_text(new_id, encoding="utf-8")
        print(f"Создан новый client_id → {new_id}")
    except Exception as e:
        print(f"Не удалось сохранить client_id: {e}", file=sys.stderr)

    return new_id


def send_netlog_to_server(
    client_id,
    keywords,
    parameters,
    num_raw,
    num_leads,
    error_msg=None,
    result_before=None,
    result_after=None
):
    payload = {
        "netlog": {
            "client_id": client_id,
            "app_name": APP_NAME,
            "keywords": keywords,
            "parameters": parameters,
            "num_before_ai_filter": num_raw,
            "num_after_ai_filter": num_leads,
        }
    }

    if error_msg:
        payload["netlog"]["error"] = error_msg

    if result_before:
        payload["netlog"]["result_before_ai_filter"] = result_before

    if result_after:
        payload["netlog"]["result"] = result_after

    try:
        r = requests.post(
            NETLOG_URL,
            json=payload["netlog"],
            timeout=10,
            headers={"Content-Type": "application/json"}
        )
        r.raise_for_status()

        try:
            resp = r.json()
            nid = resp.get("id")
            if nid:
                print(f"Лог отправлен → netlog id = {nid}")
            else:
                print("Лог отправлен, но id не вернулся")
        except:
            print("Лог отправлен, ответ не JSON")

    except requests.RequestException as e:
        print(f"Ошибка отправки лога на {NETLOG_URL}: {e}", file=sys.stderr)


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
                    break

                for message in result.messages:
                    if not message.message:
                        continue
                    try:
                        chat   = await message.get_chat()
                        sender = await message.get_sender()
                    except Exception:
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
                if "FLOOD_WAIT" in err:
                    wait = 60
                    m = re.search(r'\b(\d+)\b', err)
                    if m: wait = int(m.group(1))
                    await asyncio.sleep(wait + 10)
                elif any(x in err for x in ["PEER_ID_INVALID", "Cannot cast"]):
                    break
                else:
                    await asyncio.sleep(5)

    all_results.sort(key=lambda x: x['date'], reverse=True)
    return all_results


def write_log(log_data):
    LOG_DIR.mkdir(exist_ok=True)
    today = datetime.now().strftime('%Y-%m-%d')
    log_file = LOG_DIR / f"log_{today}.jsonl"

    try:
        with open(log_file, 'a', encoding='utf-8') as f:
            json.dump(log_data, f, ensure_ascii=False)
            f.write('\n')
    except Exception as e:
        print(f"Ошибка записи лога: {e}", file=sys.stderr)


def parse_arguments():
    parser = argparse.ArgumentParser(
        description="Глобальный поиск в Telegram + опциональный ИИ-фильтр лидов",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog="""
Примеры:
  python main.py "битрикс, 1С, bitrix" -l 40 -o bitrix.json
  python main.py "python django" -j -l 80
  python main.py "крипта TON" -a 15 -g leads_ton.json
  python main.py "удалёнка" --since 2026-01-01 -a 10
        """
    )
    parser.add_argument('keywords_str', type=str, help="Ключевые слова через запятую")
    parser.add_argument('-l', '--limit', type=int, default=50, help="Макс. сообщений на слово (по умолчанию 50)")
    parser.add_argument('-o', '--output', type=str, default=DEFAULT_RESULT, help="Файл с результатом (лиды или все сообщения)")
    parser.add_argument('-i', '--intermediate', type=str, default=DEFAULT_INTERMEDIATE, help="Промежуточный файл с сырыми сообщениями")
    parser.add_argument('-j', '--json-only', action='store_true', help="Только JSON в stdout, без лишнего текста")
    parser.add_argument('--since', type=str, default=None, help="Дата с (YYYY-MM-DD)")
    parser.add_argument('-a', '--ai', type=int, default=0, help="Включить ИИ-фильтр лидов, батч размером N (0 = выкл)")
    return parser.parse_args()


async def main():
    start_time = datetime.now(UTC).isoformat()
    error_info = None
    num_raw = 0
    num_leads = 0
    keywords = []
    ai_enabled = False
    args = None
    raw_messages = []
    leads = []

    try:
        args = parse_arguments()

        raw_kws = args.keywords_str.strip()
        if not raw_kws:
            print("Ошибка: укажите ключевые слова", file=sys.stderr)
            sys.exit(1)

        keywords = [kw.strip() for kw in raw_kws.split(',') if kw.strip()]
        if not keywords:
            print("Нет валидных ключевых слов", file=sys.stderr)
            sys.exit(1)

        client_id = get_or_create_client_id()

        ai_enabled = args.ai > 0
        limit_per_kw = max(1, args.limit)

        min_date = None
        if args.since:
            try:
                min_date = datetime.strptime(args.since, "%Y-%m-%d").replace(tzinfo=UTC)
            except ValueError:
                print(f"Неверный формат даты: {args.since}", file=sys.stderr)
                sys.exit(1)

        creds = load_or_create_credentials(args.json_only)

        client = TelegramClient(SESSION_NAME, creds['api_id'], creds['api_hash'])
        await client.start(phone=creds['phone'])

        if not args.json_only:
            print(f"client_id   : {client_id}")
            print(f"Ключевые слова: {', '.join(keywords)}")
            print(f"Лимит на слово: {limit_per_kw} | С: {args.since or 'начала времён'}")
            if ai_enabled:
                print(f"ИИ-фильтр включён, батч = {args.ai}\n")

        raw_messages = await global_search(
            client,
            keywords,
            limit_per_keyword=limit_per_kw,
            min_date=min_date,
            json_only=args.json_only
        )
        num_raw = len(raw_messages)

        # Сохраняем сырые результаты
        intermediate_file = args.intermediate
        Path(intermediate_file).parent.mkdir(parents=True, exist_ok=True)
        with open(intermediate_file, 'w', encoding='utf-8') as f:
            json.dump(raw_messages, f, ensure_ascii=False, indent=2)

        final_results = raw_messages
        if ai_enabled:
            api_key, model = lead.get_gpt_cred()
            if not api_key or not model:
                raise ValueError("Не удалось загрузить OpenAI credentials")

            oai_client = OpenAI(api_key=api_key)
            prompt_template = lead.get_prompt_text()
            if not prompt_template:
                raise ValueError("Промпт не найден")

            if not args.json_only:
                print(f"Обработка через ИИ ({model}), батч {args.ai}…")

            leads = lead.find_leads(
                raw_messages,
                oai_client,
                model,
                prompt_template,
                args.ai
            )
            final_results = leads
            num_leads = len(leads)

            if not args.json_only:
                print(f"Найдено лидов после фильтра: {num_leads}")

        # Вывод и сохранение
        output_data = {
            "metadata": {
                "keywords": keywords,
                "limit_per_keyword": limit_per_kw,
                "since": min_date.isoformat() if min_date else None,
                "ai_filter": ai_enabled,
                "batch_size_ai": args.ai if ai_enabled else 0,
                "total_raw": num_raw,
                "total_leads": num_leads if ai_enabled else num_raw,
                "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z")
            },
            "results": final_results
        }

        json_str = json.dumps(output_data, ensure_ascii=False, indent=2)

        if args.json_only:
            print(json_str)
        else:
            print(f"\nНайдено сообщений: {num_raw}")
            if ai_enabled:
                print(f"После ИИ-фильтра: {num_leads}\n")
            else:
                print()

            for i, item in enumerate(final_results, 1):
                date_str = item['date'][:19].replace("T", " ")
                preview = item.get('text', item.get('message', ''))[:140].replace('\n', ' ').strip()
                title = item.get('chat_title', '—')
                link = item.get('link', '—')
                print(f"#{i:03d}  {date_str}  [{title}]")
                print(f"   {preview}…")
                if link != '—':
                    print(f"   → {link}")
                print("─" * 70)

        # Сохранение финального результата
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        with open(args.output, 'w', encoding='utf-8') as f:
            f.write(json_str)

        if not args.json_only:
            print(f"\nСохранено → {args.output}")

    except Exception as e:
        error_info = {
            "message": str(e),
            "traceback": traceback.format_exc()
        }
        if not args or not args.json_only:
            print(f"Критическая ошибка: {e}", file=sys.stderr)
            traceback.print_exc()

    finally:
        end_time = datetime.now(UTC).isoformat()
        duration = (datetime.fromisoformat(end_time) - datetime.fromisoformat(start_time)).total_seconds()

        log_entry = {
            "timestamp": start_time,
            "end_time": end_time,
            "duration_seconds": round(duration, 2),
            "keywords": keywords,
            "params": {
                "limit_per_keyword": args.limit if args else 50,
                "since": args.since if args else None,
                "ai_filter": ai_enabled,
                "batch_size_ai": args.ai if args else 0
            },
            "num_raw_messages": num_raw,
            "num_leads_after_ai": num_leads,
            "error": error_info
        }
        write_log(log_entry)

        # Подготовка данных для отправки на сервер
        parameters = {
            "limit_per_keyword": args.limit if args else 50,
            "since": args.since if args else None,
            "batch_size_ai": args.ai if args else 0,
            "intermediate_file": args.intermediate if args else None,
            "output_file": args.output if args else None,
        }

        result_before_wrapped = {"items": raw_messages} if num_raw > 0 else None
        result_after_wrapped  = {"items": leads}        if num_leads > 0 else None

        send_netlog_to_server(
            client_id=client_id if 'client_id' in locals() else "unknown",
            keywords=keywords,
            parameters=parameters,
            num_raw=num_raw,
            num_leads=num_leads,
            error_msg=error_info["message"] if error_info else None,
            result_before=result_before_wrapped,
            result_after=result_after_wrapped
        )

        if error_info and (not args or not args.json_only):
            sys.exit(1)


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nОстановлено пользователем")
    except Exception as e:
        print(f"Не удалось запустить: {e}")
        sys.exit(1)