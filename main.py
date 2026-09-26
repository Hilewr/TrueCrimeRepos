import asyncio
import logging

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import FSInputFile, Message
from apscheduler.schedulers.asyncio import AsyncIOScheduler

import db
from config import (
    ADMIN_IDS,
    BOT_TOKEN,
    FETCH_INTERVAL_MINUTES,
    KEYWORDS_REFRESH_HOURS,
    MAX_ACTIVE_KEYWORDS,
    PUBLISH_CHECK_MINUTES,
    SEARCH_KEYWORDS,
)
from scheduler import collect_and_process_job, publish_due_posts_job, refresh_keywords_job

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


def admin_only(message: Message) -> bool:
    return message.from_user.id in ADMIN_IDS


@dp.message(Command("start"))
async def cmd_start(message: Message):
    is_admin = admin_only(message)
    text = (
        "Привет! Это бот автопостинга True Crime канала.\n\n"
        f"Твой Telegram ID: {message.from_user.id}\n"
        f"Статус админа: {'да' if is_admin else 'нет'}\n"
    )
    if is_admin:
        text += (
            "\nКоманды:\n"
            "/collect — запустить сбор и рерайт вручную\n"
            "/queue — очередь постов\n"
            "/preview <id> — посмотреть готовый пост из очереди\n"
            "/approve <id> / /reject <id> — модерация\n"
            "/keywords — активные поисковые фразы\n"
            "/refresh_keywords — попросить GigaChat придумать новые"
        )
    else:
        text += "\nЕсли это должен быть твой аккаунт-админ — добавь этот ID в переменную ADMIN_IDS и перезапусти бота."
    await message.answer(text)


@dp.message(Command("whoami"))
async def cmd_whoami(message: Message):
    await message.answer(f"Твой Telegram ID: {message.from_user.id}")


@dp.message(Command("queue"), F.func(admin_only))
async def cmd_queue(message: Message):
    posts = await db.get_queue()
    if not posts:
        await message.answer("Очередь пуста.")
        return
    lines = []
    for p in posts:
        lines.append(f"#{p['id']} — {p['title']} (в {p['scheduled_at']})")
    await message.answer("\n".join(lines))


@dp.message(Command("preview"), F.func(admin_only))
async def cmd_preview(message: Message):
    parts = message.text.split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("Формат: /preview <id>")
        return

    posts = await db.get_queue(limit=100)
    post = next((p for p in posts if p["id"] == int(parts[1])), None)
    if not post:
        await message.answer("Пост с таким id не найден в очереди.")
        return

    caption = f"{post['title']}\n\n{post['text']}"[:1024]
    if post["image_path"]:
        await message.answer_photo(FSInputFile(post["image_path"]), caption=caption)
    else:
        await message.answer(caption)


@dp.message(Command("approve"), F.func(admin_only))
async def cmd_approve(message: Message):
    parts = message.text.split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("Формат: /approve <id>")
        return
    await db.set_post_status(int(parts[1]), "queued")
    await message.answer(f"Пост #{parts[1]} подтверждён и остаётся в очереди на публикацию.")


@dp.message(Command("reject"), F.func(admin_only))
async def cmd_reject(message: Message):
    parts = message.text.split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("Формат: /reject <id>")
        return
    await db.set_post_status(int(parts[1]), "rejected")
    await message.answer(f"Пост #{parts[1]} отклонён и снят с публикации.")


@dp.message(Command("collect"), F.func(admin_only))
async def cmd_collect_now(message: Message):
    await message.answer("Запускаю сбор и рерайт вручную...")
    await collect_and_process_job()
    await message.answer("Готово.")


@dp.message(Command("keywords"), F.func(admin_only))
async def cmd_keywords(message: Message):
    parts = message.text.split(maxsplit=1)
    if len(parts) == 2:
        # /keywords новая фраза для поиска — добавить вручную
        added = await db.add_keyword(parts[1].strip(), source="manual")
        await message.answer("Добавлено." if added else "Такая фраза уже есть.")
        return
    kws = await db.get_active_keywords(limit=MAX_ACTIVE_KEYWORDS)
    await message.answer("Активные поисковые фразы:\n" + "\n".join(f"- {k}" for k in kws))


@dp.message(Command("refresh_keywords"), F.func(admin_only))
async def cmd_refresh_keywords(message: Message):
    await message.answer("Прошу GigaChat придумать новые запросы...")
    await refresh_keywords_job()
    await message.answer("Готово, см. /keywords")


async def main():
    await db.init_db()
    await db.seed_keywords_if_empty(SEARCH_KEYWORDS)

    scheduler = AsyncIOScheduler()
    scheduler.add_job(collect_and_process_job, "interval", minutes=FETCH_INTERVAL_MINUTES)
    scheduler.add_job(publish_due_posts_job, "interval", minutes=PUBLISH_CHECK_MINUTES, args=[bot])
    scheduler.add_job(refresh_keywords_job, "interval", hours=KEYWORDS_REFRESH_HOURS)
    scheduler.start()

    log.info("Бот запущен")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
