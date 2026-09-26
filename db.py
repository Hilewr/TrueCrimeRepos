import aiosqlite
import time

from config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS articles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT UNIQUE NOT NULL,
    source TEXT,
    raw_title TEXT,
    raw_text TEXT,
    status TEXT NOT NULL DEFAULT 'new',   -- new -> rewritten -> failed
    fetched_at INTEGER
);

CREATE TABLE IF NOT EXISTS keywords (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    phrase TEXT UNIQUE NOT NULL,
    source TEXT NOT NULL DEFAULT 'seed',  -- seed / generated
    active INTEGER NOT NULL DEFAULT 1,
    added_at INTEGER
);

CREATE TABLE IF NOT EXISTS posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    article_id INTEGER,
    title TEXT,
    text TEXT,
    image_path TEXT,
    status TEXT NOT NULL DEFAULT 'queued', -- queued -> published / rejected
    scheduled_at INTEGER,
    published_at INTEGER,
    FOREIGN KEY(article_id) REFERENCES articles(id)
);
"""


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(SCHEMA)
        await db.commit()


async def seed_keywords_if_empty(seed_phrases: list[str]):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT COUNT(*) FROM keywords")
        row = await cur.fetchone()
        if row[0] > 0:
            return
        for phrase in seed_phrases:
            await db.execute(
                "INSERT OR IGNORE INTO keywords (phrase, source, added_at) VALUES (?, 'seed', ?)",
                (phrase, int(time.time())),
            )
        await db.commit()


async def add_keyword(phrase: str, source: str = "generated") -> bool:
    """Возвращает True, если фраза была новой и добавилась."""
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "INSERT OR IGNORE INTO keywords (phrase, source, added_at) VALUES (?, ?, ?)",
            (phrase, source, int(time.time())),
        )
        await db.commit()
        return cur.rowcount > 0


async def get_active_keywords(limit: int = 40) -> list[str]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT phrase FROM keywords WHERE active = 1 ORDER BY added_at DESC LIMIT ?",
            (limit,),
        )
        rows = await cur.fetchall()
        return [r[0] for r in rows]


async def article_exists(url: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT 1 FROM articles WHERE url = ?", (url,))
        return await cur.fetchone() is not None


async def add_article(url: str, source: str, title: str, text: str) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "INSERT OR IGNORE INTO articles (url, source, raw_title, raw_text, fetched_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (url, source, title, text, int(time.time())),
        )
        await db.commit()
        return cur.lastrowid


async def get_new_articles(limit: int = 10):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM articles WHERE status = 'new' ORDER BY fetched_at ASC LIMIT ?",
            (limit,),
        )
        return await cur.fetchall()


async def set_article_status(article_id: int, status: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE articles SET status = ? WHERE id = ?", (status, article_id))
        await db.commit()


async def add_post(article_id: int, title: str, text: str, image_path: str, scheduled_at: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "INSERT INTO posts (article_id, title, text, image_path, scheduled_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (article_id, title, text, image_path, scheduled_at),
        )
        await db.commit()
        return cur.lastrowid


async def get_due_posts():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM posts WHERE status = 'queued' AND scheduled_at <= ? ORDER BY scheduled_at ASC",
            (int(time.time()),),
        )
        return await cur.fetchall()


async def get_queue(limit: int = 20):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM posts WHERE status = 'queued' ORDER BY scheduled_at ASC LIMIT ?",
            (limit,),
        )
        return await cur.fetchall()


async def set_post_status(post_id: int, status: str):
    async with aiosqlite.connect(DB_PATH) as db:
        ts = int(time.time()) if status == "published" else None
        if ts:
            await db.execute(
                "UPDATE posts SET status = ?, published_at = ? WHERE id = ?", (status, ts, post_id)
            )
        else:
            await db.execute("UPDATE posts SET status = ? WHERE id = ?", (status, post_id))
        await db.commit()


async def count_queued_today() -> int:
    day_start = int(time.time()) - int(time.time()) % 86400
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT COUNT(*) FROM posts WHERE scheduled_at >= ? AND status != 'rejected'",
            (day_start,),
        )
        row = await cur.fetchone()
        return row[0] if row else 0
