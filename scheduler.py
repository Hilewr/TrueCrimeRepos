import logging
import time

from aiogram import Bot
from aiogram.types import FSInputFile

import db
import image_gen
import parser as article_parser
from config import CHANNEL_ID, POSTS_PER_DAY
from rewriter import GigaChatClient

log = logging.getLogger(__name__)
_gigachat = GigaChatClient()


async def collect_and_process_job():
    """Раз в FETCH_INTERVAL_MINUTES: тянем новые статьи, рерайтим, генерим картинку,
    ставим в очередь на публикацию с равномерным распределением по дню."""
    added = await article_parser.collect_new_articles()
    log.info("Найдено новых статей: %s", added)

    already_today = await db.count_queued_today()
    slots_left = max(POSTS_PER_DAY - already_today, 0)
    if slots_left == 0:
        log.info("Дневной лимит постов уже набран, рерайт откладываем")
        return

    articles = await db.get_new_articles(limit=slots_left)
    if not articles:
        return

    day_seconds = 86400
    interval = day_seconds // max(POSTS_PER_DAY, 1)
    now = int(time.time())

    for i, article in enumerate(articles):
        result = await _gigachat.rewrite(article["raw_title"], article["raw_text"])
        if result is None:
            await db.set_article_status(article["id"], "failed")
            continue

        image_path = await image_gen.generate_image(result["image_prompt"])
        scheduled_at = now + interval * (already_today + i + 1)

        await db.add_post(
            article_id=article["id"],
            title=result["title"],
            text=result["body"],
            image_path=image_path,
            scheduled_at=scheduled_at,
        )
        await db.set_article_status(article["id"], "rewritten")
        log.info("Пост поставлен в очередь: %s", result["title"])


async def refresh_keywords_job():
    """Раз в KEYWORDS_REFRESH_HOURS: просит GigaChat придумать новые поисковые
    фразы и добавляет их в пул — это и есть автоматизация самого поиска тем,
    без ручного подбора запросов человеком."""
    existing = await db.get_active_keywords(limit=200)
    new_phrases = await _gigachat.generate_keywords(existing, n=10)
    added = 0
    for phrase in new_phrases:
        if await db.add_keyword(phrase, source="generated"):
            added += 1
    log.info("Добавлено новых поисковых фраз: %s", added)


async def publish_due_posts_job(bot: Bot):
    """Раз в PUBLISH_CHECK_MINUTES: публикует всё, чему пришло время."""
    due = await db.get_due_posts()
    for post in due:
        caption = f"{post['title']}\n\n{post['text']}"[:1024]
        try:
            if post["image_path"]:
                await bot.send_photo(
                    CHANNEL_ID, FSInputFile(post["image_path"]), caption=caption
                )
            else:
                await bot.send_message(CHANNEL_ID, caption)
            await db.set_post_status(post["id"], "published")
            log.info("Опубликован пост #%s", post["id"])
        except Exception as e:
            log.error("Не удалось опубликовать пост #%s: %s", post["id"], e)
