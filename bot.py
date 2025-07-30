#!/usr/bin/env python3
"""
Jarvis v1.0.69 — ChatGPT-only core + robust “Jarvis restart” handler

Features:
 • All private text messages go to api.chatgpt(prompt) (catch-all)
 • “/start” greeting, then just type anything
 • “Jarvis restart” → non-interactive git pull, shows stats/diff, hot-restarts
 • Response time appended to every reply

Usage:
 1. Create a `.env` file in this directory with:
      BOT_TOKEN=<your_telegram_bot_token>
 2. Install dependencies:
      pip install aiogram==3.4.1 safoneapi==1.0.69 python-dotenv httpx tgcrypto
 3. Run inside your project folder:
      screen -S jarvis python3 bot.py
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

import httpx
from aiogram import Bot, Dispatcher, types, F
from aiogram.enums import ParseMode, ChatType
from aiogram.filters import CommandStart
from SafoneAPI import SafoneAPI, errors as safone_errors
from dotenv import load_dotenv

# ─── CONFIGURATION ────────────────────────────────────────────────
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
if not BOT_TOKEN:
    raise RuntimeError("❌ BOT_TOKEN is not set in .env")

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
    python = sys.executable
    os.execv(python, [python] + sys.argv)

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
            hist.clear()
            hist.append(last_msg)
            retry = f"User: {last_msg['content']}\nJarvis:"
            resp = await api.chatgpt(retry)
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
    Non-interactive git pull, diff-stat, and hot-restart.
    """
    await msg.reply("🔄 Pulling latest code from Git, Master…")

    cwd = os.path.dirname(__file__)
    await msg.reply(f"📂 Working dir: `{cwd}`")

    def run(cmd):
        return subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=30
        )

    # 1) old HEAD
    try:
        old = run(["git", "rev-parse", "HEAD"]).stdout.strip()
    except Exception as e:
        return await msg.reply(f"❌ Could not read old HEAD: {e}")

    # 2) git pull
    try:
        pull = run(["git", "pull"])
        out, err = pull.stdout.strip(), pull.stderr.strip()
    except subprocess.TimeoutExpired:
        return await msg.reply("⚠️ `git pull` timed out after 30s.")
    except Exception as e:
        return await msg.reply(f"❌ `git pull` failed: {e}")

    # 3) new HEAD
    try:
        new = run(["git", "rev-parse", "HEAD"]).stdout.strip()
    except Exception as e:
        return await msg.reply(f"❌ Could not read new HEAD: {e}")

    # 4) diff-stat
    stat = run(["git", "diff", "--stat", old, new]).stdout.strip() or "✅ No changes"

    # 5) diff snippet
    diff_full = run(["git", "diff", old, new]).stdout
    snippet = diff_full[:2000]

    # 6) report
    await msg.reply(f"📦 Changes {old[:7]}→{new[:7]}:\n```{stat}```")
    if snippet:
        await msg.reply(f"🔍 Diff snippet:\n```{snippet}```")
        if len(diff_full) > len(snippet):
            await msg.reply("…and more lines omitted.")
    if err:
        await msg.reply(f"⚠️ Git stderr:\n```{err}```")

    # 7) hot-restart
    await asyncio.sleep(1)
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
    # Graceful shutdown on SIGINT/SIGTERM
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda s=sig: asyncio.create_task(shutdown()))

    await bot.delete_webhook(drop_pending_updates=True)
    logger.info("🚀 Jarvis started.")
    await dp.start_polling(bot, skip_updates=True)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("👋 Jarvis stopped by user.")
        asyncio.run(shutdown())
