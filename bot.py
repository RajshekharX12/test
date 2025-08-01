#!/usr/bin/env python3
"""
bot.py

Jarvis v1.0.76 — ChatGPT-only core + self-update, guards, logging,
memory cleanup, graceful shutdown, help trigger, plugins,
with truly infinite long-poll (no getUpdates timeouts).
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
from aiogram import Bot, Dispatcher, types, F
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode, ChatType
from aiogram.filters import CommandStart
from aiogram.exceptions import TelegramNetworkError
from SafoneAPI import SafoneAPI, errors as safone_errors
from dotenv import load_dotenv

# ─── CONFIG ─────────────────────────────────────────────────────
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
MASTER_ID = os.getenv("MASTER_ID", "").strip()

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN must be set in .env")
if not MASTER_ID.isdigit():
    raise RuntimeError("MASTER_ID must be an integer in .env")
MASTER_ID = int(MASTER_ID)

# ─── LOGGING ───────────────────────────────────────────────────
LOG_PATH = os.path.join(os.path.dirname(__file__), "bot.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_PATH, encoding="utf-8"),
    ]
)
logger = logging.getLogger("jarvis")

# ─── AI & HTTP CLIENTS ─────────────────────────────────────────
api = SafoneAPI()

# Use an aiohttp session with no timeouts for Telegram polling
aiohttp_timeout = aiohttp.ClientTimeout(total=None)
aio_session = AiohttpSession(timeout=aiohttp_timeout)

async def shutdown() -> None:
    """Close both aiohttp & bot sessions cleanly."""
    await aio_session.close()
    await bot.session.close()

def do_restart() -> None:
    """Hot-restart this script in place."""
    os.execv(sys.executable, [sys.executable] + sys.argv)

# ─── MEMORY & RATE LIMIT ───────────────────────────────────────
MAX_HISTORY = 6
histories: Dict[int, Deque[Dict[str,str]]] = {}
USER_LAST_TS: Dict[int, float] = {}
MIN_INTERVAL = 1.0  # seconds per user

async def memory_cleanup() -> None:
    """Every 10m purge users inactive >30m to avoid memory leaks."""
    while True:
        await asyncio.sleep(600)
        now = asyncio.get_event_loop().time()
        stale = [uid for uid, ts in USER_LAST_TS.items() if now - ts > 1800]
        for uid in stale:
            histories.pop(uid, None)
            USER_LAST_TS.pop(uid, None)
        if stale:
            logger.info(f"🧹 Cleaned {len(stale)} inactive sessions")

async def process_query(user_id: int, text: str) -> str:
    """Append to short history, call ChatGPT, return Jarvis’s reply."""
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
        logger.exception("Unexpected error in LLM call")
        return "🚨 Unexpected server error."

    answer = getattr(resp, "message", None) or str(resp)
    hist.append({"role":"bot","content":answer})
    return answer

# ─── TELEGRAM BOT SETUP ────────────────────────────────────────
bot = Bot(token=BOT_TOKEN, session=aio_session, parse_mode=ParseMode.MARKDOWN)
dp = Dispatcher()

# ─── SELF-UPDATE / RESTART HANDLER ─────────────────────────────
@dp.message(F.chat.type == ChatType.PRIVATE, F.text.regexp(r"(?i)^jarvis restart$"))
async def restart_handler(msg: types.Message) -> None:
    """Pull latest code, install deps, summarise diff, then restart."""
    await msg.reply("⏳ Updating in background…")

    async def _do_update(chat_id: int):
        cwd = os.path.dirname(__file__)
        def run(cmd):
            return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)

        git = run(["git","pull"])
        if git.returncode:
            return await bot.send_message(chat_id, f"❌ Git pull failed:\n{git.stderr}")

        p1 = run(["pip3","install","-r","requirements.txt"])
        if p1.returncode:
            return await bot.send_message(chat_id, f"❌ pip install failed:\n{p1.stderr}")

        run(["pip3","install","--upgrade","safoneapi"])

        old = run(["git","rev-parse","HEAD@{1}"]).stdout.strip()
        new = run(["git","rev-parse","HEAD"]).stdout.strip()
        diff = run(["git","diff", old, new]).stdout.strip() or "No changes"

        prompt = (
            f"Master, here’s the diff {old[:7]}→{new[:7]}:\n{diff}\n\n"
            "Give me a concise, file-by-file summary; skip trivial edits."
        )
        try:
            r = await api.chatgpt(prompt)
            summary = getattr(r, "message", str(r))
        except Exception as e:
            summary = f"⚠️ Summarisation failed: {e}"

        safe = f"```\n{summary[:3500]}\n```"
        await bot.send_message(chat_id, "✅ Update complete!\n\n" + safe)

        await shutdown()
        do_restart()

    asyncio.create_task(_do_update(msg.from_user.id))

# ─── PRE-RESTART GUARD ──────────────────────────────────────────
import threat   # ensures bot.py compiles before restart

# ─── HELP & CHAT HANDLERS ──────────────────────────────────────
@dp.message(CommandStart(), F.chat.type == ChatType.PRIVATE)
async def cmd_start(msg: types.Message) -> None:
    await msg.answer("👋 Greetings, Master! Jarvis is online — just say anything.")

@dp.message(
    F.chat.type == ChatType.PRIVATE,
    F.text.regexp(r"(?i)^(help|help me|what can you do)\??$")
)
async def help_cmd(msg: types.Message) -> None:
    await msg.reply(
        "🧠 I’m Jarvis! You can:\n"
        "• Ask naturally, no slash-commands needed\n"
        "• ‘Jarvis restart’ to self-update\n"
        "• ‘Jarvis logs’ for AI error analysis\n"
        "• Inline +888… for fragment.com URLs\n"
        "• ‘Jarvis review code’ for AI suggestions\n"
    )

@dp.message(
    F.chat.type == ChatType.PRIVATE,
    F.text,
    ~F.text.regexp(r"(?i)^(jarvis restart|jarvis logs|jarvis review code)$")
)
async def chat_handler(msg: types.Message) -> None:
    try:
        start = perf_counter()
        reply = await process_query(msg.from_user.id, msg.text.strip())
        elapsed = perf_counter() - start
        await msg.reply(f"{reply}\n\n⏱️ {elapsed:.2f}s")
    except Exception:
        logger.exception("Error in chat handler")
        await msg.reply("🚨 Unexpected error. Try again.")

# ─── PLUGIN AUTO-LOAD ──────────────────────────────────────────
PLUGIN_MODULES = ["fragment_url", "logs_utils", "code_review"]
loaded = []
for mod in PLUGIN_MODULES:
    try:
        __import__(mod)
        loaded.append(mod)
        logger.info(f"✅ Plugin loaded: {mod}")
    except Exception as e:
        logger.error(f"❌ Plugin {mod!r} failed to load: {e}")
        if MASTER_ID:
            asyncio.create_task(
                bot.send_message(MASTER_ID, f"⚠️ Plugin `{mod}` failed to load:\n{e}")
            )
logger.info(f"Active plugins: {loaded}")

# ─── MAIN ────────────────────────────────────────────────────────
async def main() -> None:
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(shutdown()))
    asyncio.create_task(memory_cleanup())

    # truly infinite long-poll: no getUpdates timeouts
    while True:
        try:
            await dp.start_polling(
                bot,
                skip_updates=True,
                timeout=90,
                request_timeout=90
            )
            break
        except TelegramNetworkError as e:
            if "timeout" not in str(e).lower():
                logger.warning("Network error: %s — retrying in 5s", e)
            await asyncio.sleep(5)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("👋 Jarvis stopped by user.")
        asyncio.run(shutdown())

