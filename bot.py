#!/usr/bin/env python3
"""
Jarvis v1.0.69 — Respectful Master‑servant AI with robust error handling

Features:
 • Always address the user as Master/Sir/Chief
 • Full ChatGPT integration via api.chatgpt(prompt)
 • Short‑term memory of the entire chat (capped at reasonable size)
 • Natural‑language help trigger
 • In‑memory cleanup of inactive users
 • Advanced error handling & retries
 • Graceful shutdown with HTTP client closure
 • Response time appended to each reply

Dependencies (requirements.txt):
 aiogram==3.4.1
 safoneapi==1.0.69
 python-dotenv>=1.0.0
 httpx>=0.24.0
 tgcrypto      # optional speedup
"""

import os
import logging
import asyncio
import signal
from time import perf_counter
from collections import defaultdict, deque
from datetime import datetime, timedelta
from typing import Deque, Dict, List

import httpx
from aiogram import Bot, Dispatcher, types, F
from aiogram.enums import ParseMode, ChatType
from aiogram.filters import CommandStart
from SafoneAPI import SafoneAPI, errors as safone_errors
from dotenv import load_dotenv

# ─── ENV VALIDATION ─────────────────────────────────────────────────
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
if not BOT_TOKEN:
    raise RuntimeError("❌ BOT_TOKEN is not set in .env")

# ─── LOGGING ───────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("jarvis")
logger.setLevel(logging.DEBUG)

# ─── API CLIENT & CLEAN SHUTDOWN ───────────────────────────────────
api = SafoneAPI()             # SafoneAPI v1.0.69
http_client = httpx.AsyncClient(timeout=10)

async def shutdown():
    logger.info("🔌 Shutting down HTTP client and bot session...")
    await http_client.aclose()
    await bot.session.close()
    logger.info("✅ Shutdown complete.")

# ─── MEMORY & INACTIVITY CLEANUP ──────────────────────────────────
HISTORY: Dict[int, Deque[Dict[str,str]]] = defaultdict(lambda: deque(maxlen=1000))
LAST_ACTIVE: Dict[int, datetime] = {}
MIN_INTERVAL = 1.0  # sec between messages per user

async def clean_inactive():
    while True:
        await asyncio.sleep(3600)
        cutoff = datetime.utcnow() - timedelta(hours=1)
        for uid, ts in list(LAST_ACTIVE.items()):
            if ts < cutoff:
                HISTORY.pop(uid, None)
                LAST_ACTIVE.pop(uid, None)
                logger.info(f"🧹 Cleared memory for inactive Master {uid}")

# ─── CORE AI CALL ─────────────────────────────────────────────────
async def process_query(user_id: int, text: str) -> str:
    # rate‐limit
    now = asyncio.get_event_loop().time()
    last = LAST_ACTIVE.get(user_id, 0).timestamp() if isinstance(LAST_ACTIVE.get(user_id), datetime) else 0
    if now - last < MIN_INTERVAL:
        await asyncio.sleep(MIN_INTERVAL - (now - last))
    LAST_ACTIVE[user_id] = datetime.utcnow()

    # store history
    hist = HISTORY[user_id]
    hist.append({"role": "user", "content": text})

    # build respectful system prompt
    prompt = (
        "You are Jarvis, a dutiful AI assistant. "
        "Always address the user respectfully as Master, Sir, or Chief.\n\n"
    )
    for msg in hist:
        speaker = "Master" if msg["role"] == "user" else "Jarvis"
        prompt += f"{speaker}: {msg['content']}\n"
    prompt += "Jarvis:"

    # call ChatGPT
    try:
        resp = await api.chatgpt(prompt)
    except safone_errors.GenericApiError as e:
        # retry minimal context if needed
        if "reduce the context" in str(e).lower():
            last_msg = hist[-1]
            hist.clear()
            hist.append(last_msg)
            simple = f"Master: {last_msg['content']}\nJarvis:"
            resp = await api.chatgpt(simple)
        else:
            logger.error(f"API error: {e}")
            return "🚨 Master, I encountered an AI service error. Please try again."
    except Exception as e:
        logger.exception("Unexpected error in AI call")
        return f"🚨 Master, something went wrong: {type(e).__name__}"

    answer = getattr(resp, "message", None) or str(resp)
    hist.append({"role": "bot", "content": answer})
    return answer

# ─── BOT SETUP ────────────────────────────────────────────────────
bot = Bot(token=BOT_TOKEN, parse_mode=ParseMode.MARKDOWN)
dp  = Dispatcher()

@dp.message(CommandStart(), F.chat.type == ChatType.PRIVATE)
async def cmd_start(msg: types.Message):
    await msg.answer("👋 Greetings, Master! Jarvis at your service. Speak, and I shall obey.")

@dp.message(F.chat.type == ChatType.PRIVATE, F.text)
async def chat_handler(msg: types.Message):
    start = perf_counter()
    reply = await process_query(msg.from_user.id, msg.text.strip())
    elapsed = perf_counter() - start
    # end with a respectful closer
    suffix = f"\n\n⏱️ Response time: {elapsed:.2f}s"
    await msg.reply(f"{reply}{suffix}")

# Graceful shutdown on signals
async def main():
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda s=sig: asyncio.create_task(shutdown()))
    # start cleanup task
    asyncio.create_task(clean_inactive())
    logger.info("🚀 Jarvis started: fully respectful, resilient, and ready.")
    await dp.start_polling(bot, skip_updates=True)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("👋 Master, Jarvis has been stopped by interruption.")
        # ensure shutdown
        asyncio.run(shutdown())
