#!/usr/bin/env python3
"""
Jarvis v1.0.69 — ChatGPT-only core + “Jarvis restart” auto‑pull & hot‑reload

Features:
 • All private text messages go into api.chatgpt(prompt) (no misses)
 • “/start” gives a greeting, but otherwise you just type anything
 • “Jarvis restart” will git pull, show stats/diff, then re‑exec
 • Response time appended to every reply

Dependencies (requirements.txt):
 aiogram==3.4.1
 safoneapi==1.0.69
 python-dotenv>=1.0.0
 httpx>=0.24.0
 tgcrypto      # optional speedup
"""

import os, sys, signal, logging, asyncio
from time import perf_counter
from collections import deque
from typing import Deque, Dict
from datetime import datetime, timedelta

import httpx
from aiogram import Bot, Dispatcher, types, F
from aiogram.enums import ParseMode, ChatType
from aiogram.filters import CommandStart
from SafoneAPI import SafoneAPI, errors as safone_errors
from dotenv import load_dotenv

# ─── CONFIG ─────────────────────────────────────────────────────
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set in .env")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("jarvis")

# ─── CHATGPT CLIENT ──────────────────────────────────────────────
api = SafoneAPI()        # v1.0.69, chatgpt endpoint only
http_client = httpx.AsyncClient(timeout=10)

async def shutdown() -> None:
    logger.info("🔌 Closing HTTP client + bot session…")
    await http_client.aclose()
    await bot.session.close()

def do_restart() -> None:
    python = sys.executable
    os.execv(python, [python] + sys.argv)

# ─── MEMORY & RATE LIMIT ─────────────────────────────────────────
MAX_HISTORY = 6
histories: Dict[int, Deque[Dict[str,str]]] = {}
USER_LAST_TS: Dict[int, float] = {}
MIN_INTERVAL = 1.0  # sec between user messages

# ─── CORE PROCESS_QUERY ──────────────────────────────────────────
async def process_query(user_id: int, text: str) -> str:
    # rate‑limit
    now = asyncio.get_event_loop().time()
    last = USER_LAST_TS.get(user_id, 0)
    if now - last < MIN_INTERVAL:
        await asyncio.sleep(MIN_INTERVAL - (now - last))
    USER_LAST_TS[user_id] = now

    # maintain a small rolling history
    hist = histories.setdefault(user_id, deque(maxlen=MAX_HISTORY))
    hist.append({"role":"user","content":text})

    # build prompt
    prompt = "\n".join(f"{m['role'].capitalize()}: {m['content']}" for m in hist)
    prompt += "\nJarvis:"

    # call chatgpt
    try:
        resp = await api.chatgpt(prompt)
    except safone_errors.GenericApiError as e:
        if "reduce the context" in str(e).lower() and hist:
            # retry with last message only
            last_msg = hist[-1]
            hist.clear()
            hist.append(last_msg)
            retry = f"User: {last_msg['content']}\nJarvis:"
            resp = await api.chatgpt(retry)
        else:
            logger.error(f"ChatGPT API error: {e}")
            return "🚨 AI error, please try again shortly."
    except Exception as e:
        logger.exception("Unexpected error")
        return "🚨 Unexpected server error."

    answer = getattr(resp, "message", None) or str(resp)
    hist.append({"role":"bot","content":answer})
    return answer

# ─── BOT SETUP ───────────────────────────────────────────────────
bot = Bot(token=BOT_TOKEN, parse_mode=ParseMode.MARKDOWN)
dp  = Dispatcher()

# greeting
@dp.message(CommandStart(), F.chat.type == ChatType.PRIVATE)
async def cmd_start(msg: types.Message):
    await msg.answer("👋 Greetings, Master! Jarvis is online — just say anything.")

# restart+git‑pull handler
@dp.message(F.chat.type == ChatType.PRIVATE, F.text.regexp(r"(?i)^jarvis restart$"))
async def restart_handler(msg: types.Message):
    await msg.reply("🔄 Pulling latest code…")
    cwd = os.path.dirname(__file__)

    # old HEAD
    old = (await asyncio.create_subprocess_exec(
        "git","rev-parse","HEAD", stdout=asyncio.subprocess.PIPE, cwd=cwd
    ).communicate())[0].decode().strip()

    # git pull
    pull = await asyncio.create_subprocess_exec(
        "git","pull", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, cwd=cwd
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

    # reply
    summary = stat or "✅ Already up‑to‑date."
    await msg.reply(f"📦 Changes {old[:7]}→{new[:7]}:\n```{summary}```")
    if err:
        await msg.reply(f"⚠️ Git stderr:\n```{err}```")

    # restart
    await asyncio.sleep(1)
    await msg.reply("🔄 Restarting now…")
    await shutdown()
    do_restart()

# catch‑all chat handler
@dp.message(F.chat.type == ChatType.PRIVATE, F.text)
async def chat(msg: types.Message):
    start = perf_counter()
    reply = await process_query(msg.from_user.id, msg.text.strip())
    elapsed = perf_counter() - start
    await msg.reply(f"{reply}\n\n⏱️ {elapsed:.2f}s")

# ─── MAIN ───────────────────────────────────────────────────────
async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    logger.info("🚀 Jarvis started.")
    await dp.start_polling(bot, skip_updates=True)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("👋 Jarvis stopped by user.")
        # no need to shutdown here; process ends
