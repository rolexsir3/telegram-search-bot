import asyncio
import logging
import os
from urllib.parse import quote_plus, urljoin

import httpx
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

load_dotenv()
BOT_TOKEN = os.environ["BOT_TOKEN"]

# Optional: only these Telegram user IDs can use the bot (comma-separated). Empty = anyone.
ALLOWED_USERS = {int(x) for x in os.getenv("ALLOWED_USERS", "").split(",") if x.strip()}

# ---------------------------------------------------------------------------
# EDIT THIS: the websites you want to search.
#   name     - label shown in the reply
#   url      - search URL, {q} is replaced with the keyword
#   selector - (optional) CSS selector matching result <a> tags on the search page.
#              If set, the bot fetches the page and returns the top result links.
#              If omitted, the bot just returns the search-page link (always works).
#   limit    - (optional) how many result links to return (default 3)
# ---------------------------------------------------------------------------
SITES = [
    {"name": "Wikipedia", "url": "https://en.wikipedia.org/w/index.php?search={q}",
     "selector": "ul.mw-search-results li.mw-search-result .mw-search-result-heading a"},
    {"name": "dropmms", "url": "https://dropmms.com/search/?q={q}&quick=1&type=forums_topic"},
    {"name": "GitHub", "url": "https://github.com/search?q={q}&type=repositories"},
    {"name": "Simpcity", "url": "https://simpcity.cr/results?search_query={q}"},
    {"name": "Reddit", "url": "https://www.reddit.com/search/?q={q}"},
]

HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36"}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("searchbot")


async def search_site(client: httpx.AsyncClient, site: dict, keyword: str) -> tuple[str, list[str]]:
    """Return (site_name, [links]). Falls back to the search-page URL."""
    search_url = site["url"].format(q=quote_plus(keyword))
    selector = site.get("selector")
    if not selector:
        return site["name"], [search_url]

    try:
        resp = await client.get(search_url, headers=HEADERS, timeout=15, follow_redirects=True)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        links = []
        for a in soup.select(selector):
            href = a.get("href")
            if href:
                full = urljoin(str(resp.url), href)
                if full not in links:
                    links.append(full)
            if len(links) >= site.get("limit", 3):
                break
        return site["name"], links or [search_url]
    except Exception as e:
        log.warning("%s failed: %s", site["name"], e)
        return site["name"], [search_url]


def allowed(update: Update) -> bool:
    return not ALLOWED_USERS or (update.effective_user and update.effective_user.id in ALLOWED_USERS)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not allowed(update):
        return
    await update.message.reply_text("Send me any keyword or name and I'll send back links from your sites.")


async def handle_keyword(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not allowed(update):
        return
    keyword = (update.message.text or "").strip()
    if not keyword:
        return

    await update.message.chat.send_action("typing")
    async with httpx.AsyncClient() as client:
        results = await asyncio.gather(*(search_site(client, s, keyword) for s in SITES))

    lines = [f"<b>Results for:</b> {keyword}\n"]
    for name, links in results:
        lines.append(f"<b>{name}</b>")
        lines.extend(links)
        lines.append("")

    await update.message.reply_text(
        "\n".join(lines), parse_mode=ParseMode.HTML, disable_web_page_preview=True
    )


def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_keyword))
    log.info("Bot running...")
    app.run_polling()


if __name__ == "__main__":
    main()
