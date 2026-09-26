import asyncio
import logging
import urllib.parse

import feedparser
import trafilatura
from gnews_decoder import decode_many

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


def _decode_many_sync(urls: list[str]) -> dict[str, str | None]:
    """Одним пакетным вызовом резолвит все google-news ссылки сразу —
    сам разруливает cookie-стену согласия (SOCS), из-за которой раньше
    падало 'Failed to fetch data attributes'."""
    return decode_many(urls, ceid="RU:ru")


async def collect_new_articles() -> int:
    keywords = await db.get_active_keywords()
    feed_urls = list(RSS_FEEDS) + [_keyword_feed_url(k) for k in keywords]

    added = 0
    for feed_url in feed_urls:
        try:
            parsed = await asyncio.to_thread(_parse_feed_sync, feed_url)
        except Exception as e:
            log.warning("Не удалось прочитать ленту %s: %s", feed_url, e)
            continue

        entries = [(e.get("link"), e.get("title", "")) for e in parsed.entries if e.get("link")]
        if not entries:
            continue

        google_links = [link for link, _ in entries if "news.google.com" in link]
        resolved: dict[str, str | None] = {}
        if google_links:
            try:
                resolved = await asyncio.to_thread(_decode_many_sync, google_links)
            except Exception as e:
                log.warning("Не удалось декодировать пачку ссылок Google News (%s): %s", feed_url, e)

        for raw_link, title in entries:
            if raw_link in resolved:
                link = resolved[raw_link]
                if link is None:
                    log.warning("Google News decoder не смог разрешить %s", raw_link)
                    continue
            else:
                link = raw_link

            if await db.article_exists(link):
                continue

            try:
                text = await asyncio.to_thread(_extract_text_sync, link)
            except Exception as e:
                log.warning("Не удалось извлечь текст %s: %s", link, e)
                continue

            if not text or len(text) < 200:
                continue

            await db.add_article(link, feed_url, title, text)
            added += 1

    return added
