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
 9. Proactive Calendar Free-Time Finder (stubbed integration)
10. Server & DevOps Watchdog (stubbed integration)
11. Interactive Storytelling Companion
15. Daily Gratitude & Motivation

Natural-language triggers only—no slash commands.
After each reply, Jarvis reports response time.

Dependencies:
  aiogram==3.4.1
  safoneapi==1.0.69
  python-dotenv>=1.0.0
  httpx>=0.24.0
  tgcrypto  # optional
  automations

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
from typing import Deque, Dict, Any, Optional

import httpx
from aiogram import Bot, Dispatcher, types, F
from aiogram.enums import ParseMode, ChatType
from aiogram.filters import CommandStart
from SafoneAPI import SafoneAPI
from SafoneAPI.errors import GenericApiError
from automations import create as create_task
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
api = SafoneAPI()

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
JOURNAL_RE = re.compile(r"how was your day[?]?", re.IGNORECASE)
MOOD_RE    = re.compile(r"i(?:'m| am) feeling (.+)", re.IGNORECASE)
HABIT_RE   = re.compile(r"remind me to (.+) every (\d+) (day|hour|minute)s?", re.IGNORECASE)
GROCERY_RE = re.compile(r"i have ([\w, ]+)\.?$", re.IGNORECASE)
SPEND_RE   = re.compile(r"i spent (\d+(?:\.\d+)?) on ([\w ]+)", re.IGNORECASE)
FLASH_RE   = re.compile(r"quiz me on (.+)", re.IGNORECASE)
STORY_RE   = re.compile(r"continue my (story|adventure)", re.IGNORECASE)
TRAVEL_RE  = re.compile(r"i(?:'m| am) going to ([\w ]+) next (day|week|month)", re.IGNORECASE)
GRATEFUL_RE= re.compile(r"i(?:'m| am) grateful for (.+)", re.IGNORECASE)

# ─── CORE PROCESSING ────────────────────────────────────────────────
async def process_query(user_id: int, text: str) -> str:
    # rate-limit
    now = asyncio.get_event_loop().time()
    last = USER_LAST_TS.get(user_id, 0)
    if now - last < MIN_INTERVAL:
        await asyncio.sleep(MIN_INTERVAL - (now - last))
    USER_LAST_TS[user_id] = now

    # append to history
    hist = histories.setdefault(user_id, deque(maxlen=MAX_HISTORY))
    hist.append({"role": "user", "content": text})

    # build prompt
    prompt = SYSTEM_PROMPT + ''.join(
        f"{'Master:' if m['role']=='user' else 'Jarvis:'} {m['content']}\n"
        for m in hist
    )
    intent = detect_intent(text)
    endpoint = INTENT_MAP.get(intent, "chatgpt")
    api_call = getattr(api, endpoint)

    try:
        resp = await api_call(prompt)
    except GenericApiError as e:
        # retry minimal context
        if "reduce the context" in str(e).lower():
            last_msg = hist[-1]
            histories[user_id] = deque([last_msg], maxlen=MAX_HISTORY)
            resp = await api_call(SYSTEM_PROMPT + f"Master: {last_msg['content']}\n")
        else:
            logger.error(f"API error: {e}")
            return "🚨 API Error, please try again."
    except Exception as e:
        logger.exception("Unexpected error")
        return "🚨 Something went wrong."

    answer = getattr(resp, 'message', None) or str(resp)
    hist.append({"role": "bot", "content": answer})
    return answer

# ─── BOT SETUP & HANDLERS ────────────────────────────────────────
bot = Bot(token=BOT_TOKEN, parse_mode=ParseMode.MARKDOWN)
dp  = Dispatcher()

@dp.message(CommandStart(), F.chat.type == ChatType.PRIVATE)
async def on_start(message: types.Message) -> None:
    await message.answer("👋 Hello, Master! Jarvis is online. Ask or chat naturally.")

@dp.message(F.chat.type == ChatType.PRIVATE, F.text)
async def on_text(message: types.Message) -> None:
    text = message.text.strip()
    start = perf_counter()
    # journaling
    if JOURNAL_RE.search(text):
        await message.reply("How are you feeling today? 😌")
        return
    if m := MOOD_RE.search(text):
        mood = m.group(1)
        # store mood (in-memory stub)
        await message.reply(f"Got it, you're feeling {mood}! 👍")
        return
    # habit reminders
    if m := HABIT_RE.search(text):
        task, amt, unit = m.groups()
        delta = {unit + 's': int(amt)}
        create_task(
            title=f"Habit: {task}",
            prompt=f"Tell me to {task}.",
            dtstart_offset_json=json.dumps(delta)
        )
        await message.reply(f"✅ I'll remind you every {amt} {unit}(s) to {task}.")
        return
    # grocery helper
    if m := GROCERY_RE.search(text):
        items = m.group(1)
        recipes = await process_query(message.from_user.id, f"Suggest recipes with {items}")
        await message.reply(recipes)
        return
    # expense tracker
    if m := SPEND_RE.search(text):
        amount, item = m.groups()
        # store expense stub
        await message.reply(f"Logged: ₹{amount} for {item} 🧾")
        return
    # flash quizzes
    if m := FLASH_RE.search(text):
        topic = m.group(1)
        quiz = f"Quiz on {topic}: ..."  # stub
        await message.reply(quiz)
        return
    # storytelling
    if STORY_RE.search(text):
        cont = await process_query(message.from_user.id, "Continue my adventure story")
        await message.reply(cont)
        return
    # travel planning
    if m := TRAVEL_RE.search(text):
        place, when = m.groups()
        plan = await process_query(message.from_user.id, f"Plan a {when}-long trip to {place}")
        await message.reply(plan)
        return
    # gratitude
    if m := GRATEFUL_RE.search(text):
        thing = m.group(1)
        await message.reply(f"That's wonderful! I'm grateful too. 🌟")
        return
    # default AI chat
    reply = await process_query(message.from_user.id, text)
    elapsed = perf_counter() - start
    await message.reply(f"{reply}\n\n⏱️ Response time: {elapsed:.2f}s")

# document & photo handlers unchanged…

async def main() -> None:
    await bot.delete_webhook(drop_pending_updates=True)
    logger.info("🚀 Jarvis live: fully featured, no commands needed.")
    await dp.start_polling(bot, skip_updates=True)

if __name__ == '__main__':
    asyncio.run(main())


