import os
from dotenv import load_dotenv

load_dotenv()


def _list(env_name: str) -> list[str]:
    raw = os.getenv(env_name, "")
    return [x.strip() for x in raw.split(",") if x.strip()]


BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_IDS = [int(x) for x in _list("ADMIN_IDS")]
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "0"))

GIGACHAT_AUTH_KEY = os.getenv("GIGACHAT_AUTH_KEY", "")
GIGACHAT_SCOPE = os.getenv("GIGACHAT_SCOPE", "GIGACHAT_API_PERS")

FUSIONBRAIN_API_KEY = os.getenv("FUSIONBRAIN_API_KEY", "")
FUSIONBRAIN_SECRET_KEY = os.getenv("FUSIONBRAIN_SECRET_KEY", "")

# Необязательно: конкретные RSS-ленты сайтов, которым ты доверяешь.
RSS_FEEDS = _list("RSS_FEEDS")

# Стартовые ключевые слова для автопоиска через Google News (бесплатно, без ключа).
# Если оставить пустым в .env — используются дефолтные ниже.
SEARCH_KEYWORDS = _list("SEARCH_KEYWORDS") or [
    "серийный убийца",
    "нераскрытое преступление",
    "громкое убийство расследование",
    "маньяк арестован",
    "cold case murder",
    "serial killer caught",
    "true crime investigation",
]

POSTS_PER_DAY = int(os.getenv("POSTS_PER_DAY", "4"))
DB_PATH = os.getenv("DB_PATH", "bot.db")
IMAGES_DIR = os.getenv("IMAGES_DIR", "images")
FETCH_INTERVAL_MINUTES = int(os.getenv("FETCH_INTERVAL_MINUTES", "60"))
PUBLISH_CHECK_MINUTES = int(os.getenv("PUBLISH_CHECK_MINUTES", "5"))
KEYWORDS_REFRESH_HOURS = int(os.getenv("KEYWORDS_REFRESH_HOURS", "24"))
MAX_ACTIVE_KEYWORDS = int(os.getenv("MAX_ACTIVE_KEYWORDS", "40"))

os.makedirs(IMAGES_DIR, exist_ok=True)
