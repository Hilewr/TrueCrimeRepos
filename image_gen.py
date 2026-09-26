import base64
import json
import logging
import os
import time
import uuid

import aiohttp

from config import FUSIONBRAIN_API_KEY, FUSIONBRAIN_SECRET_KEY, IMAGES_DIR

log = logging.getLogger(__name__)

FUSIONBRAIN_URL = "https://api-key.fusionbrain.ai/"
STYLE_SUFFIX = ", noir photography, grainy, desaturated, atmospheric, cinematic lighting"


async def _fusionbrain_generate(prompt: str) -> bytes | None:
    if not (FUSIONBRAIN_API_KEY and FUSIONBRAIN_SECRET_KEY):
        return None

    headers = {
        "X-Key": f"Key {FUSIONBRAIN_API_KEY}",
        "X-Secret": f"Secret {FUSIONBRAIN_SECRET_KEY}",
    }

    async with aiohttp.ClientSession(headers=headers) as session:
        try:
            async with session.get(FUSIONBRAIN_URL + "key/api/v1/models") as resp:
                resp.raise_for_status()
                models = await resp.json()
            model_id = models[0]["id"]

            params = {
                "type": "GENERATE",
                "numImages": 1,
                "width": 1024,
                "height": 1024,
                "generateParams": {"query": (prompt + STYLE_SUFFIX)[:1000]},
            }
            form = aiohttp.FormData()
            form.add_field("model_id", str(model_id))
            form.add_field("params", json.dumps(params), content_type="application/json")

            async with session.post(FUSIONBRAIN_URL + "key/api/v1/text2image/run", data=form) as resp:
                resp.raise_for_status()
                run_data = await resp.json()
            request_id = run_data["uuid"]

            for _ in range(15):
                async with session.get(
                    FUSIONBRAIN_URL + f"key/api/v1/text2image/status/{request_id}"
                ) as resp:
                    resp.raise_for_status()
                    status_data = await resp.json()
                if status_data.get("status") == "DONE":
                    b64_image = status_data["images"][0]
                    return base64.b64decode(b64_image)
                if status_data.get("status") == "FAIL":
                    log.warning("FusionBrain вернул FAIL: %s", status_data)
                    return None
                import asyncio

                await asyncio.sleep(10)

            log.warning("FusionBrain: не дождались результата за отведённые попытки")
            return None
        except Exception as e:
            log.error("Ошибка FusionBrain: %s", e)
            return None


async def _pollinations_generate(prompt: str) -> bytes | None:
    """Бесплатный вариант без ключей — https://pollinations.ai"""
    import urllib.parse

    encoded = urllib.parse.quote((prompt + STYLE_SUFFIX)[:500])
    url = f"https://image.pollinations.ai/prompt/{encoded}?width=1024&height=1024&nologo=true"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=90)) as resp:
                resp.raise_for_status()
                return await resp.read()
    except Exception as e:
        log.error("Ошибка Pollinations: %s", e)
        return None


async def generate_image(prompt: str) -> str | None:
    """Генерирует картинку и сохраняет на диск, возвращает путь к файлу или None."""
    image_bytes = await _fusionbrain_generate(prompt)
    if image_bytes is None:
        image_bytes = await _pollinations_generate(prompt)
    if image_bytes is None:
        return None

    filename = f"{uuid.uuid4().hex}.png"
    path = os.path.join(IMAGES_DIR, filename)
    with open(path, "wb") as f:
        f.write(image_bytes)
    return path
