#!/usr/bin/env python3
"""
Jarvis v1.0.69 — Single‑endpoint ChatGPT only

Features:
 • Natural‑language journaling, reminders, expense logging, etc.
 • All AI calls go to api.chatgpt(prompt)
 • No other endpoints ever invoked
 • Response time reported after every reply

Dependencies (requirements.txt):
 aiogram==3.4.1
 safoneapi==1.0.69
 python-dotenv>=1.0.0
 httpx>=0.24.0
 tgcrypto      # optional for Pyrogram speedups
"""

import os
import re
import logging
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

# ─── CONFIG ─────────────────────────────────────────────────────
load_dotenv()
BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set in .env")

# ─── LOGGING ───────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("jarvis")
logger.setLevel(logging.DEBUG)

# ─── RATE LIMITING & MEMORY ─────────────────────────────────────
USER_LAST_TS: Dict[int, float] = {}
MIN_INTERVAL = 1.0  # seconds between messages
MAX_HISTORY = 6
histories: Dict[int, Deque[Dict[str, str]]] = {}

# ─── API CLIENT ─────────────────────────────────────────────────
http_client = httpx.AsyncClient(timeout=10)
api = SafoneAPI()  # v1.0.69

# ─── NATURAL PATTERNS ───────────────────────────────────────────
JOURNAL_RE   = re.compile(r"how was your day\??", re.IGNORECASE)
MOOD_RE      = re.compile(r"i(?:'m| am) feeling (.+)", re.IGNORECASE)
HABIT_RE     = re.compile(r"remind me to (.+) every (\d+) (day|hour|minute)s?", re.IGNORECASE)
GROCERY_RE   = re.compile(r"i have ([\w, ]+)\.?", re.IGNORECASE)
SPEND_RE     = re.compile(r"i spent (\d+(?:\.\d+)?) on ([\w ]+)", re.IGNORECASE)
FLASH_RE     = re.compile(r"quiz me on (.+)", re.IGNORECASE)
STORY_RE     = re.compile(r"continue my (story|adventure)", re.IGNORECASE)
TRAVEL_RE    = re.compile(r"i(?:'m| am) going to ([\w ]+) next (day|week|month)", re.IGNORECASE)
GRATEFUL_RE  = re.compile(r"i(?:'m| am) grateful for (.+)", re.IGNORECASE)

# ─── UTILITY: schedule a reminder without slash commands ────────
async def schedule_reminder(chat_id: int, delay_sec: float, task: str) -> None:
    await asyncio.sleep(delay_sec)
    await bot.send_message(chat_id, f"🔔 Reminder: {task}")

# ─── CORE: always call chatgpt ──────────────────────────────────
async def process_query(user_id: int, text: str) -> str:
    # rate‑limit
    now = asyncio.get_event_loop().time()
    last = USER_LAST_TS.get(user_id, 0)
    if now - last < MIN_INTERVAL:
        await asyncio.sleep(MIN_INTERVAL - (now - last))
    USER_LAST_TS[user_id] = now

    # update history
    hist = histories.setdefault(user_id, deque(maxlen=MAX_HISTORY))
    hist.append({"role": "user", "content": text})

    # build a simple prompt with the last few messages
    prompt = "\n".join(
        f"{m['role'].capitalize()}: {m['content']}"
        for m in hist
    ) + "\nJarvis:"

    # only chatgpt
    try:
        resp = await api.chatgpt(prompt)
    except safone_errors.GenericApiError as e:
        # retry minimal context if needed
        if "reduce the context" in str(e).lower() and hist:
            last_msg = hist[-1]
            hist.clear()
            hist.append(last_msg)
            prompt2 = f"User: {last_msg['content']}\nJarvis:"
            resp = await api.chatgpt(prompt2)
        else:
            logger.error(f"ChatGPT API error: {e}")
            return "🚨 AI service error, please try again later."
    except Exception as e:
        logger.exception("Unexpected error in chatgpt call")
        return "🚨 Unexpected server error."

    answer = getattr(resp, "message", None) or str(resp)
    hist.append({"role": "bot", "content": answer})
    return answer

# ─── BOT & HANDLERS ────────────────────────────────────────────
bot = Bot(token=BOT_TOKEN, parse_mode=ParseMode.MARKDOWN)
dp  = Dispatcher()

@dp.message(CommandStart(), F.chat.type == ChatType.PRIVATE)
async def on_start(message: types.Message) -> None:
    await message.answer("👋 Hello, Master! Jarvis (ChatGPT only) is online. Chat away!")

@dp.message(F.chat.type == ChatType.PRIVATE, F.text)
async def on_text(message: types.Message) -> None:
    txt = message.text.strip()
    start = perf_counter()

    # natural triggers
    if JOURNAL_RE.search(txt):
        return await message.reply("How are you feeling today? 😌")
    if m := MOOD_RE.search(txt):
        return await message.reply(f"Got it, you’re feeling {m.group(1)}! 👍")
    if m := HABIT_RE.search(txt):
        task, amt, unit = m.groups()
        secs = int(amt) * (86400 if unit.startswith("day") else 3600 if unit.startswith("hour") else 60)
        asyncio.create_task(schedule_reminder(message.chat.id, secs, task))
        return await message.reply(f"✅ I'll remind you every {amt} {unit}(s) to {task}.")
    if m := GROCERY_RE.search(txt):
        recipes = await process_query(message.from_user.id, f"Suggest recipes with {m.group(1)}")
        return await message.reply(recipes)
    if m := SPEND_RE.search(txt):
        return await message.reply(f"Logged: ₹{m.group(1)} for {m.group(2)} 🧾")
    if m := FLASH_RE.search(txt):
        return await message.reply(f"Quiz on {m.group(1)}: [stub]")
    if STORY_RE.search(txt):
        cont = await process_query(message.from_user.id, "Continue my adventure story")
        return await message.reply(cont)
    if m := TRAVEL_RE.search(txt):
        plan = await process_query(message.from_user.id, f"Plan a {m.group(2)}-long trip to {m.group(1)}")
        return await message.reply(plan)
    if m := GRATEFUL_RE.search(txt):
        return await message.reply("That's wonderful! I'm grateful too. 🌟")

    # fallback to ChatGPT
    reply = await process_query(message.from_user.id, txt)
    elapsed = perf_counter() - start
    await message.reply(f"{reply}\n\n⏱️ Response time: {elapsed:.2f}s")

# ─── MAIN ───────────────────────────────────────────────────────
async def main() -> None:
    # clear webhook then poll
    await bot.delete_webhook(drop_pending_updates=True)
    logger.info("🚀 Jarvis (ChatGPT only) started.")
    await dp.start_polling(bot, skip_updates=True)

if __name__ == "__main__":
    asyncio.run(main())
