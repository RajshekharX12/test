#!/usr/bin/env python3
"""
Jarvis v1.0.70 — ChatGPT‑only core + self‑update & logging plugins
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

import httpx
from aiogram import Bot, Dispatcher, types, F
from aiogram.enums import ParseMode, ChatType
from aiogram.filters import CommandStart
from SafoneAPI import SafoneAPI, errors as safone_errors
from dotenv import load_dotenv

# ─── CONFIG ────────────────────────────────────────────────
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN must be set in .env")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("jarvis")

# ─── API CLIENT & HTTP SESSION ─────────────────────────────
api = SafoneAPI()               # chatgpt-only
http_client = httpx.AsyncClient(timeout=10)

async def shutdown() -> None:
    """Graceful shutdown: close http client and bot."""
    await http_client.aclose()
    await bot.session.close()

def do_restart() -> None:
    """Hot‑restart via execv."""
    os.execv(sys.executable, [sys.executable] + sys.argv)

# ─── MEMORY & RATE LIMIT ────────────────────────────────────
MAX_HISTORY = 6
histories: Dict[int, Deque[Dict[str,str]]] = {}
USER_LAST_TS: Dict[int, float] = {}
MIN_INTERVAL = 1.0  # per‑user seconds

async def process_query(user_id: int, text: str) -> str:
    """Build short history + query → ChatGPT → answer."""
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

# ─── TELEGRAM BOT SETUP ──────────────────────────────────────
bot = Bot(token=BOT_TOKEN, parse_mode=ParseMode.MARKDOWN)
dp  = Dispatcher()

@dp.message(CommandStart(), F.chat.type == ChatType.PRIVATE)
async def cmd_start(msg: types.Message) -> None:
    await msg.answer("👋 Greetings, Master! Jarvis is online — just say anything.")

@dp.message(F.chat.type == ChatType.PRIVATE, F.text.regexp(r"(?i)^jarvis restart$"))
async def restart_handler(msg: types.Message) -> None:
    """Self‑update from Git + pip + restart."""
    await msg.reply("🔄 Pulling latest code…")
    cwd = os.path.dirname(__file__)
    def run(cmd):
        return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    pull = run(["git","pull"])
    if pull.returncode != 0:
        return await msg.reply(f"❌ Git pull failed:\n```{pull.stderr}```")
    await msg.reply(f"✅ Git pull done:\n```{pull.stdout}```")
    await msg.reply("🔧 Installing dependencies…")
    deps = run(["pip3","install","-r","requirements.txt"])
    if deps.returncode != 0:
        return await msg.reply(f"❌ `pip install -r requirements.txt` failed:\n```{deps.stderr}```")
    await msg.reply("✅ Dependencies installed.")
    await msg.reply("⬆️ Upgrading safoneapi…")
    up = run(["pip3","install","--upgrade","safoneapi"])
    if up.returncode != 0:
        await msg.reply(f"⚠️ safoneapi upgrade failed:\n```{up.stderr}```")
    else:
        await msg.reply("✅ safoneapi is up to date.")
    old = run(["git","rev-parse","HEAD@{1}"]).stdout.strip()
    new = run(["git","rev-parse","HEAD"]).stdout.strip()
    stat = run(["git","diff","--stat", old, new]).stdout.strip() or "No changes"
    await msg.reply(f"📦 Changes {old[:7]}→{new[:7]}:\n```{stat}```")
    await msg.reply("🔄 Restarting…")
    await shutdown()
    do_restart()

@dp.message(
    F.chat.type == ChatType.PRIVATE,
    F.text,
    ~F.text.regexp(r"(?i)^(jarvis restart|jarvis logs)$")
)
async def chat_handler(msg: types.Message) -> None:
    start = perf_counter()
    reply = await process_query(msg.from_user.id, msg.text.strip())
    elapsed = perf_counter() - start
    await msg.reply(f"{reply}\n\n⏱️ {elapsed:.2f}s")

# ─── PLUGIN IMPORTS ───────────────────────────────────────────
import fragment_url    # Inline‑number handler
import logs_utils      # “Jarvis logs” handler

# ─── MAIN ──────────────────────────────────────────────────────
async def main() -> None:
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(shutdown()))
    await dp.start_polling(bot, skip_updates=True)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("👋 Jarvis stopped by user.")
        asyncio.run(shutdown())
