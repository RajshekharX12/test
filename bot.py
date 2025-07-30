#!/usr/bin/env python3
"""
Jarvis v1.0.69 — Top‑notch AI chat with minimal overhead

Features:
 • Natural‑language conversation only
 • All AI calls go to api.chatgpt(prompt)
 • Optional short memory of last few messages
 • Response time included in replies

Dependencies:
 aiogram==3.4.1
 safoneapi==1.0.69
 python-dotenv>=1.0.0
 httpx>=0.24.0
 tgcrypto      # optional speedup
"""

import os
import logging
import asyncio
from time import perf_counter
from collections import deque
from typing import Deque, Dict

from aiogram import Bot, Dispatcher, types, F
from aiogram.enums import ParseMode, ChatType
from aiogram.filters import CommandStart
from SafoneAPI import SafoneAPI, errors as safone_errors
from dotenv import load_dotenv

# ─── CONFIG ─────────────────────────────────────────────────────
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN must be set in .env")

# ─── LOGGING ───────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("jarvis")

# ─── MEMORY & RATE LIMIT ────────────────────────────────────────
MAX_HISTORY = 6
histories: Dict[int, Deque[Dict[str,str]]] = {}
USER_LAST_TS: Dict[int, float] = {}
MIN_INTERVAL = 1.0  # seconds between messages

# ─── API CLIENT ─────────────────────────────────────────────────
api = SafoneAPI()  # uses chatgpt under the hood

# ─── CORE QUERY ────────────────────────────────────────────────
async def process_query(user_id: int, text: str) -> str:
    now = asyncio.get_event_loop().time()
    last = USER_LAST_TS.get(user_id, 0)
    if now - last < MIN_INTERVAL:
        await asyncio.sleep(MIN_INTERVAL - (now - last))
    USER_LAST_TS[user_id] = now

    # optional short memory
    hist = histories.setdefault(user_id, deque(maxlen=MAX_HISTORY))
    hist.append({"role":"user","content":text})

    # build prompt
    prompt = "\n".join(
        f"{m['role'].capitalize()}: {m['content']}" for m in hist
    ) + "\nJarvis:"

    # call ChatGPT only
    try:
        resp = await api.chatgpt(prompt)
    except safone_errors.GenericApiError as e:
        if "reduce the context" in str(e).lower() and hist:
            last_msg = hist[-1]
            hist.clear()
            hist.append(last_msg)
            resp = await api.chatgpt(f"User: {last_msg['content']}\nJarvis:")
        else:
            logger.error(f"ChatGPT error: {e}")
            return "🚨 AI service error, please try again later."
    except Exception as e:
        logger.exception("Unexpected error")
        return "🚨 Unexpected server error."

    answer = getattr(resp, "message", None) or str(resp)
    hist.append({"role":"bot","content":answer})
    return answer

# ─── BOT SETUP ─────────────────────────────────────────────────
bot = Bot(token=BOT_TOKEN, parse_mode=ParseMode.MARKDOWN)
dp  = Dispatcher()

@dp.message(CommandStart(), F.chat.type == ChatType.PRIVATE)
async def welcome(message: types.Message) -> None:
    await message.answer("👋 Hey there! Jarvis is here — just say anything.")

@dp.message(F.chat.type == ChatType.PRIVATE, F.text)
async def chat(message: types.Message) -> None:
    start = perf_counter()
    reply = await process_query(message.from_user.id, message.text.strip())
    elapsed = perf_counter() - start
    await message.reply(f"{reply}\n\n⏱️ {elapsed:.2f}s")

# ─── MAIN ───────────────────────────────────────────────────────
async def main() -> None:
    await bot.delete_webhook(drop_pending_updates=True)
    logger.info("🚀 Jarvis started: ChatGPT only.")
    await dp.start_polling(bot, skip_updates=True)

if __name__ == "__main__":
    asyncio.run(main())
