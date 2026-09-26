import json
import logging
import ssl
import time
import uuid

import aiohttp

from config import GIGACHAT_AUTH_KEY, GIGACHAT_SCOPE

log = logging.getLogger(__name__)

OAUTH_URL = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
CHAT_URL = "https://gigachat.devices.sberbank.ru/api/v1/chat/completions"

# ВАЖНО: серверы Сбера используют сертификат Минцифры РФ, который не входит
# в стандартный набор доверенных CA. Правильный путь — установить в систему
# сертификат НУЦ Минцифры (https://gigachat.devices.sberbank.ru/CA.pem) и
# указать его ниже вместо verify_ssl=False. Для быстрого старта/теста можно
# отключить проверку, но для прод-сервера это небезопасно.
VERIFY_SSL = False

SYSTEM_PROMPT = (
    "Ты — редактор Telegram-канала про true crime (реальные преступления, "
    "расследования, биографии). Тебе дают сырой текст статьи (может быть на "
    "любом языке).\n\n"
    "Сначала проверь: статья описывает РЕАЛЬНОЕ преступление, расследование, "
    "арест, суд или биографию реального преступника? Если это анонс/рецензия "
    "фильма, сериала, книги, игры, подкаста, или любой другой материал НЕ про "
    "реальное произошедшее событие — ответь СТРОГО:\n"
    '{"skip": true, "reason": "..."}\n\n'
    "Если статья подходит, твоя задача:\n"
    "1. Перевести суть на русский и полностью переписать своими словами — "
    "не копировать формулировки и структуру оригинала, только факты.\n"
    "2. Сделать атмосферный, но фактологически точный пост для Telegram "
    "(1000–1500 символов), без выдуманных подробностей.\n"
    "3. Придумать короткое (до 20 слов) описание сцены на английском для "
    "генератора изображений — нейтральная атмосфера (тёмный переулок, старый "
    "дом, архив дела и т.п.), БЕЗ насилия, крови и реальных имён/лиц.\n\n"
    "Ответь СТРОГО в виде JSON без markdown-разметки и пояснений:\n"
    '{"skip": false, "title": "...", "body": "...", "image_prompt": "..."}'
)


class GigaChatClient:
    def __init__(self):
        self._token = None
        self._token_expires_at = 0

    async def _get_token(self, session: aiohttp.ClientSession) -> str:
        if self._token and time.time() < self._token_expires_at - 60:
            return self._token

        headers = {
            "Authorization": f"Basic {GIGACHAT_AUTH_KEY}",
            "RqUID": str(uuid.uuid4()),
            "Content-Type": "application/x-www-form-urlencoded",
        }
        async with session.post(
            OAUTH_URL, headers=headers, data={"scope": GIGACHAT_SCOPE}, ssl=VERIFY_SSL
        ) as resp:
            resp.raise_for_status()
            data = await resp.json()

        self._token = data["access_token"]
        # expires_at у GigaChat приходит в миллисекундах
        self._token_expires_at = data["expires_at"] / 1000
        return self._token

    async def rewrite(self, raw_title: str, raw_text: str) -> dict | None:
        """Возвращает {"title", "body", "image_prompt"}, или None если статья
        не подошла (ошибка запроса, парсинга, ИЛИ GigaChat решил, что это не
        про реальное преступление, а например анонс фильма/сериала)."""
        raw_text = raw_text[:6000]  # не раздувать запрос

        async with aiohttp.ClientSession() as session:
            token = await self._get_token(session)
            payload = {
                "model": "GigaChat",
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": f"Заголовок: {raw_title}\n\nТекст статьи:\n{raw_text}",
                    },
                ],
                "temperature": 0.7,
            }
            headers = {"Authorization": f"Bearer {token}"}
            try:
                async with session.post(
                    CHAT_URL, headers=headers, json=payload, ssl=VERIFY_SSL
                ) as resp:
                    resp.raise_for_status()
                    data = await resp.json()
            except Exception as e:
                log.error("Ошибка запроса к GigaChat: %s", e)
                return None

        try:
            content = data["choices"][0]["message"]["content"]
            # модель иногда оборачивает JSON в ```json ... ``` — на всякий случай чистим
            content = content.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            parsed = json.loads(content)

            if parsed.get("skip"):
                log.info("GigaChat пропустил статью не по теме (%s): %s", raw_title, parsed.get("reason"))
                return None

            assert "title" in parsed and "body" in parsed and "image_prompt" in parsed
            return parsed
        except Exception as e:
            log.error("Не удалось распарсить ответ GigaChat: %s | content=%r", e, data)
            return None

    async def generate_keywords(self, existing: list[str], n: int = 10) -> list[str]:
        """Просит GigaChat придумать новые поисковые фразы для Google News,
        не повторяющие уже использованные — это и есть автоматизация поиска тем."""
        prompt = (
            f"Придумай {n} новых, разнообразных коротких поисковых запросов "
            "(2-5 слов, на русском и английском вперемешку) для поиска свежих "
            "новостей в жанре true crime: расследования убийств, аресты "
            "серийных преступников, громкие суды, нераскрытые дела, похищения. "
            "Не повторяй и не перефразируй уже использованные запросы:\n"
            + "\n".join(f"- {e}" for e in existing[:40])
            + "\n\nОтветь СТРОГОJSON-массивом строк без пояснений: "
            '["запрос 1", "запрос 2", ...]'
        )

        async with aiohttp.ClientSession() as session:
            token = await self._get_token(session)
            payload = {
                "model": "GigaChat",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.9,
            }
            headers = {"Authorization": f"Bearer {token}"}
            try:
                async with session.post(
                    CHAT_URL, headers=headers, json=payload, ssl=VERIFY_SSL
                ) as resp:
                    resp.raise_for_status()
                    data = await resp.json()
            except Exception as e:
                log.error("Ошибка запроса генерации ключевых слов: %s", e)
                return []

        try:
            content = data["choices"][0]["message"]["content"]
            content = content.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            phrases = json.loads(content)
            return [p.strip() for p in phrases if isinstance(p, str) and p.strip()]
        except Exception as e:
            log.error("Не удалось распарсить список ключевых слов: %s | content=%r", e, data)
            return []
