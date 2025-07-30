#!/usr/bin/env python3
"""
Jarvis v1.0.69 — fast mode with only supported endpoints

Endpoints used:
  • api.chatgpt(prompt)
  • api.gemini(prompt)
  • api.llama3(prompt)
  • api.asq(prompt)
"""

import os
import logging
import asyncio
from collections import deque

import httpx
from aiogram import Bot, Dispatcher, types, F
from aiogram.enums import ParseMode, ChatType
from aiogram.filters import CommandStart
from SafoneAPI import SafoneAPI
from SafoneAPI.errors import GenericApiError
from dotenv import load_dotenv

# ─── CONFIG ────────────────────────────────────────────────────
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set in .env")

# ─── LOGGING ───────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("jarvis")

# ─── API CLIENT ─────────────────────────────────────────────────
http_client = httpx.AsyncClient(timeout=10)
api = SafoneAPI()  # only using the four core endpoints

# ─── MEMORY ────────────────────────────────────────────────────
MAX_HISTORY = 6
histories: dict[int, deque[dict[str, str]]] = {}

SYSTEM_PROMPT = (
    "You are Jarvis, a professional AI assistant. "
    "The user is your master. Respond helpfully in friendly English with emojis.\n\n"
)

# ─── INTENT MAP ─────────────────────────────────────────────────
# Only these four endpoints
INTENT_MAP = {
    "technical": "chatgpt",  # code, debugging, explanations
    "creative":  "gemini",   # stories, brainstorming
    "privacy":   "llama3",    # private or fine‑tuned tasks
    "factual":   "asq"        # quick Q&A
}

def detect_intent(text: str) -> str:
    txt = text.lower()
    if any(tok in txt for tok in ["debug", "error", "how", "why", "explain"]):
        return "technical"
    if any(txt.startswith(cmd) for cmd in ["write", "poem", "story", "compose", "brainstorm"]):
        return "creative"
    if "private" in txt or "confidential" in txt:
        return "privacy"
    # default factual Q&A
    return "factual"

async def process_query(user_id: int, text: str) -> str:
    history = histories.setdefault(user_id, deque(maxlen=MAX_HISTORY))
    history.append({"role": "user", "content": text})

    prompt = SYSTEM_PROMPT + "".join(
        f"{'Master:' if m['role']=='user' else 'Jarvis:'} {m['content']}\n"
        for m in history
    )

    intent = detect_intent(text)
    method_name = INTENT_MAP[intent]
    api_call = getattr(api, method_name)

    try:
        resp = await api_call(prompt)
    except GenericApiError as e:
        if "reduce the context" in str(e).lower():
            last = history[-1]
            histories[user_id] = deque([last], maxlen=MAX_HISTORY)
            prompt = SYSTEM_PROMPT + f"Master: {last['content']}\n"
            resp = await api_call(prompt)
        else:
            raise

    answer = getattr(resp, "message", None) or str(resp)
    history.append({"role": "bot", "content": answer})
    return answer

# ─── BOT SETUP ────────────────────────────────────────────────
bot = Bot(token=BOT_TOKEN, parse_mode=ParseMode.MARKDOWN)
dp = Dispatcher()

@dp.message(CommandStart(), F.chat.type == ChatType.PRIVATE)
async def on_start(message: types.Message):
    await message.answer(
        "👋 Hello, Master! I'm Jarvis v1.0.69. "
        "Just type anything and I'll choose chatgpt, gemini, llama3, or asq intelligently."
    )

@dp.message(F.chat.type == ChatType.PRIVATE, F.text)
async def on_message(message: types.Message):
    reply = await process_query(message.from_user.id, message.text.strip())
    await message.reply(reply)

async def main():
    # clear any webhook and start polling
    await bot.delete_webhook(drop_pending_updates=True)
    logger.info("🚀 Jarvis started: only chatgpt, gemini, llama3, asq.")
    await dp.start_polling(bot, skip_updates=True)

if __name__ == "__main__":
    asyncio.run(main())


