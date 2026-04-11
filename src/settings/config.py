import os

from dotenv import load_dotenv

load_dotenv()

# Database
POSTGRES_URI = os.environ["DATABASE_URL"]

# Proxies
WEBSHARE_URL = os.environ["WEBSHARE_URL"]

# Scraping
SCRAPE_INTERVAL = int(os.getenv("SCRAPE_INTERVAL", "120"))
MAX_PAGES = int(os.getenv("MAX_PAGES", "3"))
PAGE_SIZE = 50
