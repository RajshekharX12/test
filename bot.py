#!/usr/bin/env python3
"""
Jarvis v1.0.69 — Clean, chat‑only AI with inline feedback buttons

Features:
 • Single ChatGPT endpoint (api.chatgpt)
 • Catch‑all private‑chat handler (no slash commands)
 • Respectful “Master/Sir/Chief” persona
 • In‑memory chat history (pruned after 1 h idle)
 • Natural “help” trigger
 • Inline buttons “👍 Thanks” and “🔄 Retry” after every reply
 • “Jarvis restart” → git pull, diff‑stat & snippet, hot‑restart
 • Graceful shutdown of HTTP & bot sessions
 • Response time on every reply

Usage:
 1. Set BOT_TOKEN in .env  
 2. `pip install -r requirements.txt`  
 3. `screen -S jarvis python3 bot.py`
"""

import os
import sys
import signal
import logging
import asyncio
from time import perf_counter
from collections import defaultdict, deque
from datetime import datetime, timedelta
from typing import Deque, Dict

import httpx
from aiogram import Bot, Dispatcher, types, F
from aiogram.enums import ParseMode, ChatType
from aiogram.filters import CommandStart
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from SafoneAPI import SafoneAPI, errors as safone_errors
from dotenv import load_dotenv

# ─── CONFIGURATION ────────────────────────────────────────────────
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set in .env")

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("jarvis")

# ─── GLOBALS ──────────────────────────────────────────────────────
api = SafoneAPI()            # ChatGPT-only
http_client = httpx.AsyncClient(timeout=10)

HISTORY: Dict[int, Deque[Dict[str, str]]] = defaultdict(lambda: deque())
LAST_ACTIVE: Dict[int, datetime] = {}
MIN_INTERVAL     = 1.0                  # secs between messages per user
INACTIVITY_LIMIT = timedelta(hours=1)   # clear history after 1h idle
MAX_HISTORY      = 6                    # rolling context size

# Inline feedback keyboard
FEEDBACK_KEYBOARD = InlineKeyboardMarkup(
    inline_keyboard=[
        [
            InlineKeyboardButton("👍 Thanks", callback_data="feedback_thanks"),
            InlineKeyboardButton("🔄 Retry",  callback_data="feedback_retry")
        ]
    ]
)

# ─── UTILITIES ────────────────────────────────────────────────────
async def shutdown() -> None:
    """Cleanly close HTTP client and bot session."""
    logger.info("🔌 Shutting down HTTP client and bot session…")
    await http_client.aclose()
    await bot.session.close()
    logger.info("✅ Shutdown complete.")

def do_restart() -> None:
    """Re‑executes this script in‑place (hot‑restart)."""
    python = sys.executable
    os.execv(python, [python] + sys.argv)

async def clean_inactive_users() -> None:
    """Purge chat histories of users idle >INACTIVITY_LIMIT every 10 min."""
    while True:
        await asyncio.sleep(600)
        cutoff = datetime.utcnow() - INACTIVITY_LIMIT
        for uid, ts in list(LAST_ACTIVE.items()):
            if ts < cutoff:
                HISTORY.pop(uid, None)
                LAST_ACTIVE.pop(uid, None)
                logger.info(f"🧹 Cleared memory for inactive Master {uid}")

# ─── CORE LLM INTERACTION ─────────────────────────────────────────
async def process_query(user_id: int, text: str) -> str:
    """Build a prompt, call ChatGPT, handle errors, record history, return reply."""
    # rate‑limit
    now_ts  = asyncio.get_event_loop().time()
    last_ts = LAST_ACTIVE.get(user_id, datetime.utcnow()).timestamp()
    if now_ts - last_ts < MIN_INTERVAL:
        await asyncio.sleep(MIN_INTERVAL - (now_ts - last_ts))
    LAST_ACTIVE[user_id] = datetime.utcnow()

    # record user message
    hist = HISTORY[user_id]
    hist.append({"role": "user", "content": text})
    if len(hist) > MAX_HISTORY:
        hist.popleft()

    # help trigger
    if any(kw in text.lower() for kw in ("help", "what can you do", "how to use")):
        return (
            "🤖 *Jarvis Help*\n"
            " • Type any question—no prefix needed.\n"
            " • I address you as Master/Sir/Chief.\n"
            " • I remember our chat & show response times.\n"
            " • Use the buttons below for feedback or retry.\n"
            " • Say “Jarvis restart” to pull updates & reboot."
        )

    # build respectful prompt
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
        if "reduce the context" in str(e).lower() and hist:
            last_msg = hist[-1]
            hist.clear(); hist.append(last_msg)
            retry = f"Master: {last_msg['content']}\nJarvis:"
            resp = await api.chatgpt(retry)
        else:
            logger.error(f"ChatGPT API error: {e}")
            return "🚨 Master, AI service error—please try again."
    except Exception as e:
        logger.exception("Unexpected error in AI call")
        return f"🚨 Master, something went wrong: {type(e).__name__}"

    answer = getattr(resp, "message", None) or str(resp)
    hist.append({"role": "bot", "content": answer})
    return answer

# ─── TELEGRAM BOT SETUP ───────────────────────────────────────────
bot = Bot(token=BOT_TOKEN, parse_mode=ParseMode.MARKDOWN)
dp  = Dispatcher()

@dp.message(CommandStart(), F.chat.type == ChatType.PRIVATE)
async def cmd_start(message: types.Message) -> None:
    await message.answer("👋 Greetings, Master! Jarvis is online. Just say anything.")

@dp.message(F.chat.type == ChatType.PRIVATE, F.text.regexp(r"(?i)^jarvis restart$"))
async def restart_handler(message: types.Message) -> None:
    """On “Jarvis restart”: git pull, show stats & diff, then hot‑restart."""
    await message.reply("🔄 Pulling latest code from Git, Master…")
    cwd = os.path.dirname(__file__)

    # old HEAD
    old = (await asyncio.create_subprocess_exec(
        "git","rev-parse","HEAD", stdout=asyncio.subprocess.PIPE, cwd=cwd
    ).communicate())[0].decode().strip()

    # git pull
    pull = await asyncio.create_subprocess_exec(
        "git","pull", stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE, cwd=cwd
    )
    out, err = await pull.communicate()
    out, err = out.decode().strip(), err.decode().strip()

    # new HEAD
    new = (await asyncio.create_subprocess_exec(
        "git","rev-parse","HEAD", stdout=asyncio.subprocess.PIPE, cwd=cwd
    ).communicate())[0].decode().strip()

    # diff‑stat
    stat = (await asyncio.create_subprocess_exec(
        "git","diff","--stat", old, new, stdout=asyncio.subprocess.PIPE, cwd=cwd
    ).communicate())[0].decode().strip()

    # diff snippet
    diff_full = (await asyncio.create_subprocess_exec(
        "git","diff", old, new, stdout=asyncio.subprocess.PIPE, cwd=cwd
    ).communicate())[0].decode()
    snippet = diff_full[:3000]

    # reply summary
    summary = stat or "✅ Already up‑to‑date."
    await message.reply(f"📦 Changes {old[:7]}→{new[:7]}:\n```{summary}```")
    if snippet:
        await message.reply(f"🔍 Diff snippet:\n```{snippet}```")
        if len(diff_full) > len(snippet):
            await message.reply("…and more lines omitted.")
    if err:
        await message.reply(f"⚠️ Git stderr:\n```{err}```")

    # hot‑restart
    await asyncio.sleep(1)
    await message.reply("🔄 Restarting now, Master…")
    await shutdown()
    do_restart()

@dp.message(F.chat.type == ChatType.PRIVATE, F.text)
async def chat_handler(message: types.Message) -> None:
    """Catch‑all private‑chat handler with inline feedback buttons."""
    start = perf_counter()
    reply = await process_query(message.from_user.id, message.text.strip())
    elapsed = perf_counter() - start
    await message.reply(
        f"{reply}\n\n⏱️ {elapsed:.2f}s",
        reply_markup=FEEDBACK_KEYBOARD
    )

@dp.callback_query(F.data == "feedback_thanks")
async def feedback_thanks(call: CallbackQuery) -> None:
    await call.answer("🙏 Happy to help, Master!", show_alert=False)

@dp.callback_query(F.data == "feedback_retry")
async def feedback_retry(call: CallbackQuery) -> None:
    """Re-run the last user query on button press."""
    user_id = call.from_user.id
    hist = HISTORY.get(user_id)
    if not hist:
        return await call.answer("❌ No message to retry.", show_alert=True)
    # find last user message
    last_user = next((m for m in reversed(hist) if m["role"]=="user"), None)
    if not last_user:
        return await call.answer("❌ No user message found.", show_alert=True)
    start = perf_counter()
    new_reply = await process_query(user_id, last_user["content"])
    elapsed = perf_counter() - start
    await call.message.answer(
        f"{new_reply}\n\n⏱️ {elapsed:.2f}s",
        reply_markup=FEEDBACK_KEYBOARD
    )
    await call.answer()

# ─── MAIN & GRACEFUL SHUTDOWN ─────────────────────────────────────
async def main() -> None:
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda s=sig: asyncio.create_task(shutdown()))
    asyncio.create_task(clean_inactive_users())
    await bot.delete_webhook(drop_pending_updates=True)
    logger.info("🚀 Jarvis started: clean, chat‑only + inline feedback + hot‑reload.")
    await dp.start_polling(bot, skip_updates=True)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("👋 Master, Jarvis has been stopped by interruption.")
        asyncio.run(shutdown())
