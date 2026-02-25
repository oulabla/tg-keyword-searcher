import json
import os
import sys
import yaml
import time
import argparse
from itertools import islice
from typing import List, Dict, Tuple
from openai import OpenAI


PROMPT_FILENAME = 'prompt.txt'
GPT_CRED_FILENAME = 'gpt_cred.yaml'


def get_gpt_cred() -> Tuple[str, str]:
    if os.path.exists(GPT_CRED_FILENAME):
        with open(GPT_CRED_FILENAME, "r", encoding="utf-8") as f:
            cred = yaml.safe_load(f)

        api_key = cred.get('api_key')
        model = cred.get('model')
        if len(api_key) > 0 and len(model) > 0:
           print(f"Токен загружен из файла {GPT_CRED_FILENAME}")
        return api_key, model

    api_key = input("Введите API KEY для ChatGPT: ").strip()
    if not api_key:
        print("API KEY не может быть пустым")
        sys.exit(1)

    model = input("Введите модель по умолчанию для ChatGPT: ").strip()
    if not model:
        print("Будет использована gpt-5-mini")
        model = 'gpt-5-mini'

    save = input("Сохранить в файл для следующих запусков? (y/n): ").lower()
    if save in ('y', 'yes'):
        with open(GPT_CRED_FILENAME, "w", encoding="utf-8") as f:
            yaml.dump({
                "api_key": api_key,
                "model": model,
            }, f, default_flow_style=False)
        print(f"Данные для работы с ChatGPT сохранёны в {GPT_CRED_FILENAME}")

    return api_key, model


def get_prompt_text() -> str:
    if os.path.exists(PROMPT_FILENAME):
        with open(PROMPT_FILENAME, "r", encoding="utf-8") as f:
            prompt = f.read().strip()
        if prompt:
            return prompt

    print("Введите текст и нажмите Ctrl+D (Linux/Mac) или Ctrl+Z+Enter (Windows):")
    prompt = sys.stdin.read()
    print("промпт принят")
    prompt = prompt.strip('\x1A')
    prompt = prompt.strip()

    if not prompt:
        print("Промпт не может быть пустым")
        sys.exit(1)

    save = input("Сохранить промпт в файл для следующих запусков? (y/n): ").lower()
    if save in ('y', 'yes'):
        with open(PROMPT_FILENAME, "w", encoding="utf-8") as f:
            f.write(prompt)
        print(f"Промпт сохранён в {PROMPT_FILENAME}")

    return prompt

def batched(iterable: List, n: int):
    it = iter(iterable)
    while chunk := list(islice(it, n)):
        yield chunk


def find_leads(messages: List[Dict], client: OpenAI, model: str, prompt_template: str, batch_size: int) -> List[Dict]:
    all_leads = []

    for batch_num, batch in enumerate(batched(messages, batch_size), 1):
        print(f"Батч {batch_num} ({len(batch)} сообщений)")

        batch_payload = []
        text_to_meta = {}

        for msg in batch:
            text = msg.get('text') or msg.get('message') or msg.get('content') or ""
            if not text.strip():
                continue

            payload_item = {
                "text": text,
                "link": msg.get("link", "")
            }
            batch_payload.append(payload_item)

            # сохраняем дату для последующего сопоставления
            text_to_meta[text] = {
                "date": msg.get("date"),
                "link": msg.get("link")
            }

        if not batch_payload:
            continue

        full_prompt = prompt_template + "\n" + json.dumps(batch_payload, ensure_ascii=False, indent=2)

        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {
                        "role": "system",
                        "content": "Отвечай только валидным JSON-массивом."
                    },
                    {"role": "user", "content":
                        full_prompt + """
                        Оставь только сообщения содержащие лиды
  Ответь СТРОГО в формате JSON:
  [{
    "confidence": 85,
    "reason": "краткое объяснение",
    "key_indicators": ["спрашивает цену", "хочет купить"],
    "date": "оригинальная дата",
    "text": "оригинальный текст из сообщения", 
    "link": "оригинальный link из сообщения", 
  }...]
  
                        """
                     }
                ]
            )

            leads = json.loads(response.choices[0].message.content)

            if not isinstance(leads, list):
                raise ValueError("Модель вернула не массив")

            print(f"  Найдено лидов: {len(leads)}")

            for lead in leads:
                original_text = lead.get("text", "")
                meta = text_to_meta.get(original_text, {})

                lead["date"] = meta.get("date")
                lead["link"] = meta.get("link")  # гарантируем оригинальный линк

                all_leads.append(lead)

        except Exception as e:
            print(f"  Ошибка батча: {e}")

        time.sleep(0.6)

    return all_leads


def main():
    parser = argparse.ArgumentParser(description='Поиск потенциальных лидов в сообщениях')
    parser.add_argument('-o', '--output', default='messages.json')
    parser.add_argument('-n', '--n', type=int, default=10)
    parser.add_argument('--leads', default='leads_only.json')
    parser.add_argument('--model', default='')
    args = parser.parse_args()

    api_key, ai_model = get_gpt_cred()
    if not api_key:
        raise ValueError("API ключ не найден")
    if not ai_model:
        raise ValueError("Модель не указана")

    client = OpenAI(api_key=api_key)

    prompt_template = get_prompt_text()
    if not prompt_template:
        raise ValueError("Промпт не найден")

    filename = args.output

    with open(filename, 'r', encoding='utf-8') as f:
        messages: List[Dict] = json.load(f)

    print(f"Загружено {len(messages)} сообщений. Батч размером {args.n}")
    print(f"Модель: {ai_model}\n")

    all_leads = find_leads(messages, client, ai_model, prompt_template, args.n)

    with open(args.leads, 'w', encoding='utf-8') as f:
        json.dump(all_leads, f, ensure_ascii=False, indent=2)

    print(f"\nГотово. Найдено лидов: {len(all_leads)}")
    print(f"Файл лидов: {args.leads}")

if __name__ == "__main__":
    main()
