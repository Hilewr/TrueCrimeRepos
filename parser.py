import asyncio
import logging
import urllib.parse

import feedparser
import trafilatura
from googlenewsdecoder.decoder_async import GoogleDecoderAsync

import db
from config import RSS_FEEDS

log = logging.getLogger(__name__)

GOOGLE_NEWS_RSS = "https://news.google.com/rss/search?q={q}&hl=ru&gl=RU&ceid=RU:ru"


def _keyword_feed_url(phrase: str) -> str:
    return GOOGLE_NEWS_RSS.format(q=urllib.parse.quote(phrase))


def _parse_feed_sync(feed_url: str):
    return feedparser.parse(feed_url)


def _extract_text_sync(url: str) -> str | None:
    downloaded = trafilatura.fetch_url(url)
    if not downloaded:
        return None
    return trafilatura.extract(downloaded, include_comments=False, include_tables=False)


async def _resolve_link(decoder: GoogleDecoderAsync, link: str) -> str | None:
    """Google News заворачивает реальный URL статьи в свой редирект-адрес
    (news.google.com/rss/articles/...), который упирается в экран согласия
    на cookie и зацикливается в редиректах. Достаём настоящий URL напрямую
    через внутренний API Google, без хождения по редиректам."""
    if "news.google.com" not in link:
        return link
    try:
        result = await decoder.decode_google_news_url(link, interval=1)
    except Exception as e:
        log.warning("Не удалось декодировать ссылку Google News %s: %s", link, e)
        return None
    if result.get("success"):
        return result["decoded_url"]
    log.warning("Google News decoder вернул ошибку для %s: %s", link, result.get("message"))
    return None


async def collect_new_articles() -> int:
    """Проходит по фиксированным RSS-лентам (если заданы) и по автопоиску
    через Google News на основе ключевых слов из БД. Добавляет ещё не
    виденные статьи в БД. Возвращает количество добавленных статей."""
    keywords = await db.get_active_keywords()
    feed_urls = list(RSS_FEEDS) + [_keyword_feed_url(k) for k in keywords]

    added = 0
    async with GoogleDecoderAsync() as decoder:
        for feed_url in feed_urls:
            try:
                parsed = await asyncio.to_thread(_parse_feed_sync, feed_url)
            except Exception as e:
                log.warning("Не удалось прочитать ленту %s: %s", feed_url, e)
                continue

            for entry in parsed.entries:
                raw_link = entry.get("link")
                title = entry.get("title", "")
                if not raw_link:
                    continue

                link = await _resolve_link(decoder, raw_link)
                if not link:
                    continue

                if await db.article_exists(link):
                    continue

                try:
                    text = await asyncio.to_thread(_extract_text_sync, link)
                except Exception as e:
                    log.warning("Не удалось извлечь текст %s: %s", link, e)
                    continue

                if not text or len(text) < 200:
                    # слишком короткая/пустая статья (часто это заглушка пейволла) — пропускаем
                    continue

                await db.add_article(link, feed_url, title, text)
                added += 1

    return added
