#!/usr/bin/env python3
"""
bot.py

Jarvis v1.0.73 — ChatGPT-only core + self-update, top-error logging,
and robust long-poll timeouts via custom AiohttpSession.
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

import aiohttp
import httpx
from aiogram import Bot, Dispatcher, types, F
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode, ChatType
from aiogram.filters import CommandStart
from SafoneAPI import SafoneAPI, errors as safone_errors
from dotenv import load_dotenv

# ─── CONFIG ─────────────────────────────────────────────────────
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
MASTER_ID = os.getenv("MASTER_ID", "").strip()

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN must be set in .env")
if not MASTER_ID.isdigit():
    raise RuntimeError("MASTER_ID must be a numeric string in .env")
MASTER_ID = int(MASTER_ID)

# ─── LOGGING ───────────────────────────────────────────────────
log_path = os.path.join(os.path.dirname(__file__), "bot.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(log_path, encoding="utf-8")
    ]
)
logger = logging.getLogger("jarvis")

# ─── API CLIENT & HTTP SESSION ─────────────────────────────────
api = SafoneAPI()

# Keep a separate httpx client for external API calls:
http_client = httpx.AsyncClient(
    timeout=httpx.Timeout(connect=5.0, read=90.0, write=5.0, pool=None)
)

# Create a custom Aiogram session with aiohttp timeouts:
aiohttp_timeout = aiohttp.ClientTimeout(
    total=90.0,      # max time for any request
    connect=5.0,     # connect timeout
    sock_connect=5.0,
    sock_read=90.0   # read timeout (long‐poll)
)
aio_session = AiohttpSession(timeout=aiohttp_timeout)

async def shutdown() -> None:
    """Graceful shutdown: close HTTP clients & bot session."""
    await http_client.aclose()
    await bot.session.close()

def do_restart() -> None:
    """Hot-restart the script in-place."""
    os.execv(sys.executable, [sys.executable] + sys.argv)

# ─── MEMORY, RATE LIMIT & CLEANUP ─────────────────────────────
MAX_HISTORY = 6
histories: Dict[int, Deque[Dict[str,str]]] = {}
USER_LAST_TS: Dict[int, float] = {}
MIN_INTERVAL = 1.0

async def memory_cleanup() -> None:
    """Every 10m, purge users inactive for >30m."""
    while True:
        await asyncio.sleep(600)
        now = asyncio.get_event_loop().time()
        stale = [uid for uid, ts in USER_LAST_TS.items() if now - ts > 1800]
        for uid in stale:
            histories.pop(uid, None)
            USER_LAST_TS.pop(uid, None)
        if stale:
            logger.info(f"🧹 Cleaned {len(stale)} inactive users")

async def process_query(user_id: int, text: str) -> str:
    now = asyncio.get_event_loop().time()
    last = USER_LAST_TS.get(user_id, 0)
    if now - last < MIN_INTERVAL:
        await asyncio.sleep(MIN_INTERVAL - (now - last))
    USER_LAST_TS[user_id] = now

    hist = histories.setdefault(user_id, deque(maxlen=MAX_HISTORY))
    hist.append({"role":"user","content":text})
    prompt = "\n".join(f"{m['role'].capitalize()}: {m['content']}" for m in hist) + "\nJarvis:"

    try:
        resp = await api.chatgpt(prompt)
    except safone_errors.GenericApiError as e:
        if "reduce the context" in str(e).lower() and hist:
            last_msg = hist[-1]
            hist.clear(); hist.append(last_msg)
            resp = await api.chatgpt(f"User: {last_msg['content']}\nJarvis:")
        else:
            logger.error("ChatGPT API error: %s", e)
            return "🚨 AI service error, please try again later."
    except Exception:
        logger.exception("Unexpected error")
        return "🚨 Unexpected server error."

    answer = getattr(resp, "message", None) or str(resp)
    hist.append({"role":"bot","content":answer})
    return answer

# ─── TELEGRAM BOT SETUP ────────────────────────────────────────
bot = Bot(
    token=BOT_TOKEN,
    session=aio_session,             # use our custom aiohttp session
    parse_mode=ParseMode.MARKDOWN
)
dp  = Dispatcher()

# ─── RESTART LOGIC (used by threat.py) ────────────────────────
async def restart_handler(msg: types.Message) -> None:
    """
    Self-update flow (after health checks):
      • git pull
      • pip3 install -r requirements.txt
      • pip3 install --upgrade safoneapi
      • summarise diff via ChatGPT
      • restart
    """
    await msg.reply("⏳ Updating in background…")

    async def _do_update(chat_id: int):
        cwd = os.path.dirname(__file__)
        def run(cmd):
            return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)

        pull = run(["git","pull"])
        if pull.returncode != 0:
            return await bot.send_message(chat_id, f"❌ Git pull failed:\n{pull.stderr}")

        deps = run(["pip3","install","-r","requirements.txt"])
        if deps.returncode != 0:
            return await bot.send_message(chat_id, f"❌ pip install failed:\n{deps.stderr}")

        run(["pip3","install","--upgrade","safoneapi"])

        old = run(["git","rev-parse","HEAD@{1}"]).stdout.strip()
        new = run(["git","rev-parse","HEAD"]).stdout.strip()
        diff = run(["git","diff",old,new]).stdout.strip() or "No changes"

        prompt = (
            f"Master, diff {old}→{new}:\n{diff}\n\n"
            "Give a concise, file-by-file summary; skip trivial edits."
        )
        try:
            resp = await api.chatgpt(prompt)
            summary = getattr(resp,"message",str(resp))
        except Exception as e:
            summary = f"⚠️ Summarisation failed: {e}"

        safe = f"```\n{summary[:3500]}\n```"
        await bot.send_message(chat_id, "✅ Update complete!\n\n"+safe)

        await shutdown()
        do_restart()

    asyncio.create_task(_do_update(msg.from_user.id))

# ─── IMPORT THE GUARD ─────────────────────────────────────────
import threat    # preflight compile-check for restart

# ─── COMMANDS & HANDLERS ─────────────────────────────────────
@dp.message(CommandStart(), F.chat.type == ChatType.PRIVATE)
async def cmd_start(msg: types.Message):
    await msg.answer("👋 Greetings, Master! Jarvis is online — just say anything.")

@dp.message(
    F.chat.type == ChatType.PRIVATE,
    F.text.regexp(r"(?i)^(help|help me|what can you do)\??$")
)
async def help_cmd(msg: types.Message):
    await msg.reply(
        "🧠 I’m Jarvis! You can:\n"
        "• Ask naturally\n"
        "• ‘Jarvis restart’ to self-update\n"
        "• ‘Jarvis logs’ for root-cause errors\n"
        "• Inline +888… numbers for fragment.com links\n"
        "• ‘Jarvis review code’ for AI suggestions\n"
    )

@dp.message(
    F.chat.type == ChatType.PRIVATE,
    F.text,
    ~F.text.regexp(r"(?i)^(jarvis restart|jarvis logs|jarvis review code)$")
)
async def chat_handler(msg: types.Message):
    try:
        start = perf_counter()
        reply = await process_query(msg.from_user.id, msg.text.strip())
        elapsed = perf_counter() - start
        await msg.reply(f"{reply}\n\n⏱️ {elapsed:.2f}s")
    except Exception:
        logger.exception("Error in chat handler")
        await msg.reply("🚨 Unexpected error. Try again.")

# ─── PLUGINS ────────────────────────────────────────────────────
import fragment_url   # inline fragment.com URL
import logs_utils     # AI log-analysis
import code_review    # “Jarvis review code”

# ─── MAIN ────────────────────────────────────────────────────────
async def main() -> None:
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(shutdown()))
    asyncio.create_task(memory_cleanup())

    # extended polling timeouts here:
    await dp.start_polling(
        bot,
        skip_updates=True,
        timeout=90,           # how long Telegram holds each getUpdates
        request_timeout=90    # how long aiohttp waits for any response
    )

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("👋 Stopped by user.")
        asyncio.run(shutdown())
