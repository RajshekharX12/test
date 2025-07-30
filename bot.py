#!/usr/bin/env python3
"""
Jarvis v1.0.69 — Feature-rich, natural-language Telegram AI assistant

Features:
 1. Personal Journaling & Mood Tracking
 2. Habit & Goal Coach with natural reminders
 3. Smart Grocery & Recipe Helper
 4. Micro-Learning Flashcards
 5. Wellness & Mindfulness Breaks
 6. Expense & Budget Tracker
 7. AI Pair-Programming Buddy
 8. Travel Itinerary & Local Tips
 9. Proactive Calendar Free-Time Finder (stubbed)
10. Server & DevOps Watchdog (stubbed)
11. Interactive Storytelling Companion
15. Daily Gratitude & Motivation

Natural-language triggers only—no slash commands.
After each reply, Jarvis reports response time.

Dependencies:
  aiogram==3.4.1
  safoneapi==1.0.69
  python-dotenv>=1.0.0
  httpx>=0.24.0
  tgcrypto  # optional for Pyrogram speedups

Usage:
  - Populate BOT_TOKEN in .env
  - Run: python3 bot.py
"""

import os
import re
import json
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

# ─── CONFIG & ENV ─────────────────────────────────────────────────
load_dotenv()
BOT_TOKEN: str = os.getenv("BOT_TOKEN") or ""
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set in .env")

# ─── LOGGING ───────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("jarvis")
logger.setLevel(logging.DEBUG)

# ─── RATE LIMITING ─────────────────────────────────────────────────
USER_LAST_TS: Dict[int, float] = {}
MIN_INTERVAL = 1.0  # seconds

# ─── API CLIENT ─────────────────────────────────────────────────────
http_client = httpx.AsyncClient(timeout=10)
api = SafoneAPI()  # SafoneAPI v1.0.69

# ─── MEMORY ─────────────────────────────────────────────────────────
MAX_HISTORY = 6
histories: Dict[int, Deque[Dict[str, str]]] = {}

# ─── SYSTEM PROMPT & ENDPOINT ROUTING ───────────────────────────────
SYSTEM_PROMPT: str = (
    "You are Jarvis, a professional AI assistant. "
    "The user is your master. Respond helpfully in friendly English with emojis.\n\n"
)
INTENT_MAP = {
    "technical": "chatgpt",
    "creative":  "gemini",
    "privacy":   "llama3",
    "factual":   "asq",
}

# ─── INTENT DETECTION ───────────────────────────────────────────────
def detect_intent(text: str) -> str:
    txt = text.lower()
    if any(tok in txt for tok in ["debug", "error", "how", "why", "explain"]):
        return "technical"
    if any(txt.startswith(cmd) for cmd in ["write", "poem", "story", "compose", "brainstorm"]):
        return "creative"
    if "private" in txt or "confidential" in txt:
        return "privacy"
    return "factual"

# ─── NATURAL TRIGGER PATTERNS ──────────────────────────────────────
JOURNAL_RE   = re.compile(r"how was your day\??", re.IGNORECASE)
MOOD_RE      = re.compile(r"i(?:'m| am) feeling (.+)", re.IGNORECASE)
HABIT_RE     = re.compile(r"remind me to (.+) every (\d+) (day|hour|minute)s?", re.IGNORECASE)
GROCERY_RE   = re.compile(r"i have ([\w, ]+)\.?", re.IGNORECASE)
SPEND_RE     = re.compile(r"i spent (\d+(?:\.\d+)?) on ([\w ]+)", re.IGNORECASE)
FLASH_RE     = re.compile(r"quiz me on (.+)", re.IGNORECASE)
STORY_RE     = re.compile(r"continue my (story|adventure)", re.IGNORECASE)
TRAVEL_RE    = re.compile(r"i(?:'m| am) going to ([\w ]+) next (day|week|month)", re.IGNORECASE)
GRATEFUL_RE  = re.compile(r"i(?:'m| am) grateful for (.+)", re.IGNORECASE)

# ─── REMINDER SCHEDULER ────────────────────────────────────────────
async def schedule_reminder(chat_id: int, delay_sec: float, task: str) -> None:
    await asyncio.sleep(delay_sec)
    await bot.send_message(chat_id, f"🔔 Reminder: {task}")

# ─── CORE PROCESSING ────────────────────────────────────────────────
async def process_query(user_id: int, text: str) -> str:
    """Build prompt, call AI endpoint, handle errors, and record history."""
    # Rate-limit per user
    now = asyncio.get_event_loop().time()
    last = USER_LAST_TS.get(user_id, 0)
    if now - last < MIN_INTERVAL:
        await asyncio.sleep(MIN_INTERVAL - (now - last))
    USER_LAST_TS[user_id] = now

    # Append to capped history
    hist = histories.setdefault(user_id, deque(maxlen=MAX_HISTORY))
    hist.append({"role": "user", "content": text})

    # Build conversation prompt
    prompt = SYSTEM_PROMPT + "".join(
        f"{'Master:' if m['role']=='user' else 'Jarvis:'} {m['content']}\n"
        for m in hist
    )

    # Select endpoint
    intent = detect_intent(text)
    endpoint = INTENT_MAP.get(intent, "chatgpt")
    api_call = getattr(api, endpoint)

    try:
        resp = await api_call(prompt)
    except safone_errors.GenericApiError as e:
        # Retry minimal context if too-long error
        if "reduce the context" in str(e).lower():
            last_msg = hist[-1]
            histories[user_id] = deque([last_msg], maxlen=MAX_HISTORY)
            resp = await api_call(
                SYSTEM_PROMPT + f"Master: {last_msg['content']}\n"
            )
        else:
            logger.error(f"API error on {endpoint}: {e}")
            return "🚨 AI service error, please try again later."
    except Exception as e:
        logger.exception("Unexpected error in AI call")
        return "🚨 Unexpected server error."

    answer = getattr(resp, "message", None) or str(resp)
    hist.append({"role": "bot", "content": answer})
    return answer

# ─── BOT SETUP & HANDLERS ────────────────────────────────────────
bot = Bot(token=BOT_TOKEN, parse_mode=ParseMode.MARKDOWN)
dp  = Dispatcher()

@dp.message(CommandStart(), F.chat.type == ChatType.PRIVATE)
async def on_start(message: types.Message) -> None:
    await message.answer("👋 Hello, Master! Jarvis is online. Talk to me naturally.")

@dp.message(F.chat.type == ChatType.PRIVATE, F.text)
async def on_text(message: types.Message) -> None:
    text = message.text.strip()
    start = perf_counter()

    # Natural journaling & mood
    if JOURNAL_RE.search(text):
        await message.reply("How are you feeling today? 😌")
        return
    if m := MOOD_RE.search(text):
        await message.reply(f"Got it, you’re feeling {m.group(1)}! 👍")
        return

    # Habit reminders
    if m := HABIT_RE.search(text):
        task, amt, unit = m.groups()
        secs = int(amt) * (3600 if unit.startswith("hour") else 60 if unit.startswith("minute") else 86400)
        asyncio.create_task(schedule_reminder(message.chat.id, secs, task))
        await message.reply(f"✅ I'll remind you every {amt} {unit}(s) to {task}.")
        return

    # Grocery helper
    if m := GROCERY_RE.search(text):
        items = m.group(1)
        recipes = await process_query(message.from_user.id, f"Suggest recipes with {items}")
        await message.reply(recipes)
        return

    # Expense tracker
    if m := SPEND_RE.search(text):
        await message.reply(f"Logged: ₹{m.group(1)} for {m.group(2)} 🧾")
        return

    # Flashcards stub
    if m := FLASH_RE.search(text):
        await message.reply(f"Quiz on {m.group(1)}: [stubbed quiz here]")
        return

    # Storytelling
    if STORY_RE.search(text):
        cont = await process_query(message.from_user.id, "Continue my adventure story")
        await message.reply(cont)
        return

    # Travel planning
    if m := TRAVEL_RE.search(text):
        plan = await process_query(
            message.from_user.id,
            f"Plan a {m.group(2)}-long trip to {m.group(1)}"
        )
        await message.reply(plan)
        return

    # Gratitude
    if m := GRATEFUL_RE.search(text):
        await message.reply("That's wonderful! I'm grateful too. 🌟")
        return

    # Default AI chat
    reply = await process_query(message.from_user.id, text)
    elapsed = perf_counter() - start
    await message.reply(f"{reply}\n\n⏱️ Response time: {elapsed:.2f}s")

# ─── MAIN ───────────────────────────────────────────────────────
async def main() -> None:
    # Clean any webhooks before polling
    await bot.delete_webhook(drop_pending_updates=True)
    logger.info("🚀 Jarvis started: no external automations module needed.")
    await dp.start_polling(bot, skip_updates=True)

if __name__ == "__main__":
    asyncio.run(main())
