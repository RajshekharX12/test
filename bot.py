#!/usr/bin/env python3
"""
Jarvis v1.0.70 — ChatGPT‑only core + full “Jarvis restart” self‑update

Features:
 • Catch‑all private‑chat handler → api.chatgpt(prompt)
 • “/start” greeting, otherwise just type anything
 • “Jarvis restart” does:
     1) git pull
     2) pip install -r requirements.txt
     3) pip install --upgrade safoneapi
     4) show diff‑stat + snippet
     5) hot‑restart via os.execv
 • New instance sends a “back online” confirmation
 • Response time appended to every reply
"""

import os
import sys
import signal
import logging
import subprocess
import asyncio
from time import perf_counter
from collections import deque
from typing import Deque, Dict
import fragment_url
import logs_utils
import httpx
from aiogram import Bot, Dispatcher, types, F
from aiogram.enums import ParseMode, ChatType
from aiogram.filters import CommandStart
from SafoneAPI import SafoneAPI, errors as safone_errors
from dotenv import load_dotenv
import re
from aiogram.types import InlineQueryResultArticle, InputTextMessageContent

# ─── CONFIGURATION ────────────────────────────────────────────────
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
MASTER_ID = os.getenv("MASTER_ID", "").strip()  # optional: your Telegram user ID
if not BOT_TOKEN:
    raise RuntimeError("❌ BOT_TOKEN is not set in .env")
if MASTER_ID:
    MASTER_ID = int(MASTER_ID)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)
logger = logging.getLogger("jarvis")

# ─── API CLIENT & SHUTDOWN ─────────────────────────────────────────
api = SafoneAPI()                # ChatGPT-only endpoint
http_client = httpx.AsyncClient(timeout=10)

async def shutdown() -> None:
    """Cleanly close HTTP client and bot session."""
    logger.info("🔌 Shutting down HTTP client and bot session…")
    await http_client.aclose()
    await bot.session.close()

def do_restart() -> None:
    """Re-executes this script in-place (hot-restart)."""
    os.execv(sys.executable, [sys.executable] + sys.argv)

# ─── MEMORY & RATE LIMIT ─────────────────────────────────────────
MAX_HISTORY = 6
histories: Dict[int, Deque[Dict[str,str]]] = {}
USER_LAST_TS: Dict[int, float] = {}
MIN_INTERVAL = 1.0  # seconds between messages per user

# ─── CORE PROCESSING ──────────────────────────────────────────────
async def process_query(user_id: int, text: str) -> str:
    now = asyncio.get_event_loop().time()
    last = USER_LAST_TS.get(user_id, 0)
    if now - last < MIN_INTERVAL:
        await asyncio.sleep(MIN_INTERVAL - (now - last))
    USER_LAST_TS[user_id] = now

    hist = histories.setdefault(user_id, deque(maxlen=MAX_HISTORY))
    hist.append({"role": "user", "content": text})

    prompt = "\n".join(f"{m['role'].capitalize()}: {m['content']}" for m in hist)
    prompt += "\nJarvis:"

    try:
        resp = await api.chatgpt(prompt)
    except safone_errors.GenericApiError as e:
        if "reduce the context" in str(e).lower() and hist:
            last_msg = hist[-1]
            hist.clear(); hist.append(last_msg)
            resp = await api.chatgpt(f"User: {last_msg['content']}\nJarvis:")
        else:
            logger.error(f"ChatGPT API error: {e}")
            return "🚨 AI service error, please try again later."
    except Exception:
        logger.exception("Unexpected error")
        return "🚨 Unexpected server error."

    answer = getattr(resp, "message", None) or str(resp)
    hist.append({"role": "bot", "content": answer})
    return answer

# ─── TELEGRAM BOT SETUP ───────────────────────────────────────────
bot = Bot(token=BOT_TOKEN, parse_mode=ParseMode.MARKDOWN)
dp  = Dispatcher()

@dp.message(CommandStart(), F.chat.type == ChatType.PRIVATE)
async def cmd_start(msg: types.Message) -> None:
    await msg.answer("👋 Greetings, Master! Jarvis is online — just say anything.")

@dp.message(
    F.chat.type == ChatType.PRIVATE,
    F.text.regexp(r"(?i)^jarvis restart$")
)
async def restart_handler(msg: types.Message) -> None:
    """
    1) git pull
    2) pip install -r requirements.txt
    3) pip install --upgrade safoneapi
    4) show diff-stat + snippet
    5) hot-restart
    """
    await msg.reply("🔄 Pulling latest code from Git, Master…")
    cwd = os.path.dirname(__file__)
    await msg.reply(f"📂 Working dir: `{cwd}`")

    def run(cmd, timeout=120):
        return subprocess.run(
            cmd, cwd=cwd,
            capture_output=True, text=True,
            stdin=subprocess.DEVNULL, timeout=timeout
        )

    # git pull
    pull = run(["git","pull"])
    if pull.returncode != 0:
        return await msg.reply(f"❌ Git pull failed:\n```{pull.stderr.strip()}```")
    await msg.reply(f"✅ Git pull done:\n```{pull.stdout.strip()}```")

    # install requirements
    await msg.reply("🔧 Installing dependencies…")
    deps = run(["pip3","install","-r","requirements.txt"])
    if deps.returncode != 0:
        return await msg.reply(f"❌ `pip install -r requirements.txt` failed:\n```{deps.stderr}```")
    await msg.reply("✅ Dependencies installed/updated.")

    # upgrade safoneapi
    await msg.reply("⬆️ Upgrading safoneapi…")
    sa_up = run(["pip3","install","--upgrade","safoneapi"])
    if sa_up.returncode != 0:
        await msg.reply(f"⚠️ safoneapi upgrade failed:\n```{sa_up.stderr}```")
    else:
        await msg.reply("✅ safoneapi is up to date.")

    # diff-stat & snippet
    old = run(["git","rev-parse","HEAD@{1}"]).stdout.strip()
    new = run(["git","rev-parse","HEAD"]).stdout.strip()
    stat = run(["git","diff","--stat", old, new]).stdout.strip() or "✅ No changes"
    diff_full = run(["git","diff", old, new]).stdout
    snippet = diff_full[:2000]

    await msg.reply(f"📦 Changes {old[:7]}→{new[:7]}:\n```{stat}```")
    if snippet:
        await msg.reply(f"🔍 Diff snippet:\n```{snippet}```")
        if len(diff_full) > len(snippet):
            await msg.reply("…and more lines omitted.")

    # final restart message (no extra quotes!)
    await msg.reply("🔄 Restarting now, Master…")
    await shutdown()
    do_restart()

@dp.message(F.chat.type == ChatType.PRIVATE, F.text)
async def chat_handler(msg: types.Message) -> None:
    """Catch-all private-chat handler."""
    start = perf_counter()
    reply = await process_query(msg.from_user.id, msg.text.strip())
    elapsed = perf_counter() - start
    await msg.reply(f"{reply}\n\n⏱️ {elapsed:.2f}s")

async def main() -> None:
    # Optionally, notify you when Jarvis is back online
    if MASTER_ID:
        await bot.send_message(MASTER_ID, "✅ Jarvis is back online, Master.")

    # Graceful shutdown on SIGINT/SIGTERM
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(shutdown()))

    await bot.delete_webhook(drop_pending_updates=True)
    logger.info("🚀 Jarvis started.")
    await dp.start_polling(bot, skip_updates=True)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("👋 Jarvis stopped by user.")
        asyncio.run(shutdown())
