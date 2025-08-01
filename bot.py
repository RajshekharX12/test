#!/usr/bin/env python3
"""
bot.py

Jarvis v1.0.72 — minimal, no-timeout core + self-update & plugins
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

from aiogram import Bot, Dispatcher, types, F
from aiogram.enums import ParseMode, ChatType, DefaultBotProperties
from aiogram.filters import CommandStart
from SafoneAPI import SafoneAPI, errors as safone_errors
from dotenv import load_dotenv

# ─── CONFIG ─────────────────────────────────────────────────────
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
MASTER_ID = int(os.getenv("MASTER_ID", "0"))

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN must be set in .env")

# ─── LOGGING ───────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("jarvis")

# ─── API CLIENT ─────────────────────────────────────────────────
api = SafoneAPI()  # chatgpt-only

# ─── MEMORY & RATE LIMIT ───────────────────────────────────────
MAX_HISTORY = 6
MIN_INTERVAL = 1.0  # seconds per user
histories: Dict[int, Deque[Dict[str,str]]] = {}
last_ts: Dict[int, float] = {}

async def process_query(user_id: int, text: str) -> str:
    # rate limit
    now = asyncio.get_event_loop().time()
    delta = now - last_ts.get(user_id, 0)
    if delta < MIN_INTERVAL:
        await asyncio.sleep(MIN_INTERVAL - delta)
    last_ts[user_id] = now

    # short-term memory
    hist = histories.setdefault(user_id, deque(maxlen=MAX_HISTORY))
    hist.append({"role": "user", "content": text})
    prompt = "\n".join(f"{m['role'].capitalize()}: {m['content']}" for m in hist)
    prompt += "\nJarvis:"

    try:
        resp = await api.chatgpt(prompt)
    except safone_errors.GenericApiError as e:
        # reduce-context retry
        if "reduce the context" in str(e).lower() and hist:
            last = hist[-1]
            hist.clear()
            hist.append(last)
            resp = await api.chatgpt(f"User: {last['content']}\nJarvis:")
        else:
            logger.error("ChatGPT API error: %s", e)
            return "🚨 AI service error, please try again later."
    except Exception:
        logger.exception("Unexpected error")
        return "🚨 Unexpected server error."

    answer = getattr(resp, "message", None) or str(resp)
    hist.append({"role": "bot", "content": answer})
    return answer

# ─── BOT SETUP ─────────────────────────────────────────────────
bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN, timeout=60)
)
dp = Dispatcher()

# ─── RESTART HANDLER ────────────────────────────────────────────
@dp.message(F.chat.type == ChatType.PRIVATE, F.text.regexp(r"(?i)^jarvis restart$"))
async def restart_handler(msg: types.Message):
    await msg.reply("🔄 Pulling latest code…")
    cwd = os.path.dirname(__file__)
    def run(cmd):
        return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)

    pull = run(["git","pull"])
    if pull.returncode != 0:
        return await msg.reply(f"❌ Git pull failed:\n```\n{pull.stderr}\n```")
    await msg.reply(f"✅ Git pull done:\n```\n{pull.stdout}\n```")

    await msg.reply("🔧 Installing dependencies…")
    deps = run(["pip3","install","-r","requirements.txt"])
    if deps.returncode != 0:
        return await msg.reply(f"❌ pip install failed:\n```\n{deps.stderr}\n```")
    await msg.reply("✅ Dependencies installed.")

    # summarise diff
    old = run(["git","rev-parse","HEAD@{1}"]).stdout.strip()
    new = run(["git","rev-parse","HEAD"]).stdout.strip()
    diff = run(["git","diff","--stat", old, new]).stdout.strip() or "No changes"
    safe = f"```\n{diff}\n```"
    await msg.reply(f"📦 Changes {old[:7]}→{new[:7]}:\n{safe}")

    await msg.reply("🔄 Restarting…")
    # note: this will immediately replace the process
    os.execv(sys.executable, [sys.executable] + sys.argv)

# ─── START GREETING & CHAT HANDLER ─────────────────────────────
@dp.message(CommandStart(), F.chat.type == ChatType.PRIVATE)
async def cmd_start(msg: types.Message):
    await msg.answer("👋 Greetings, Master! Jarvis online — just say anything.")

@dp.message(
    F.chat.type == ChatType.PRIVATE,
    F.text,
    ~F.text.regexp(r"(?i)^(jarvis restart|jarvis logs)$")
)
async def chat_handler(msg: types.Message):
    start = perf_counter()
    reply = await process_query(msg.from_user.id, msg.text.strip())
    elapsed = perf_counter() - start
    await msg.reply(f"{reply}\n\n⏱️ {elapsed:.2f}s")

# ─── NATURAL-LANGUAGE HELP TRIGGER ─────────────────────────────
@dp.message(F.chat.type == ChatType.PRIVATE, F.text.regexp(r"(?i)^(help|what can you do)"))
async def help_handler(msg: types.Message):
    await msg.reply(
        "I can chat freely—just say anything.\n"
        "Say “jarvis restart” to self-update and restart.\n"
        "Try sending a +888 number or `Jarvis logs` to see top errors."
    )

# ─── PLUGINS ────────────────────────────────────────────────────
for name in ("fragment_url", "logs_utils", "code_review"):
    try:
        __import__(name)
        logger.info("✅ Plugin loaded: %s", name)
    except Exception as e:
        logger.error("❌ Plugin %s failed to load: %s", name, e)

# ─── MAIN ───────────────────────────────────────────────────────
async def main():
    for sig in (signal.SIGINT, signal.SIGTERM):
        asyncio.get_event_loop().add_signal_handler(sig, lambda: asyncio.create_task(bot.session.close()))
    logger.info("Start polling")
    await dp.start_polling(bot, skip_updates=True)

if __name__ == "__main__":
    asyncio.run(main())
