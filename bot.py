#!/usr/bin/env python3
"""
bot.py

Jarvis v1.0.77 — ChatGPT-only core + self-update, preflight guard,
logging plugins, memory cleanup, graceful shutdown & help trigger.
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
from aiogram.enums import ParseMode, ChatType
from aiogram.filters import CommandStart
from SafoneAPI import SafoneAPI, errors as safone_errors
from dotenv import load_dotenv

# ─── CONFIG ─────────────────────────────────────────────────────
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
MASTER_ID = os.getenv("MASTER_ID", "").strip()
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN must be set in .env")
if not MASTER_ID.isdigit():
    raise RuntimeError("MASTER_ID must be an integer in .env")
MASTER_ID = int(MASTER_ID)

# ─── LOGGING ───────────────────────────────────────────────────
LOG_PATH = os.path.join(os.path.dirname(__file__), "bot.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_PATH, encoding="utf-8"),
    ]
)
logger = logging.getLogger("jarvis")

# ─── AI CLIENT ──────────────────────────────────────────────────
api = SafoneAPI()

async def shutdown() -> None:
    """Close bot session on exit."""
    await bot.session.close()

def do_restart() -> None:
    """Hot-restart via execv."""
    os.execv(sys.executable, [sys.executable] + sys.argv)

# ─── MEMORY & RATE LIMIT ───────────────────────────────────────
MAX_HISTORY = 6
histories: Dict[int, Deque[Dict[str,str]]] = {}
USER_LAST_TS: Dict[int, float] = {}
MIN_INTERVAL = 1.0  # seconds per user

async def memory_cleanup() -> None:
    """Every 10m, purge users inactive >30m to bound memory."""
    while True:
        await asyncio.sleep(600)
        now = asyncio.get_event_loop().time()
        stale = [u for u, t in USER_LAST_TS.items() if now - t > 1800]
        for u in stale:
            histories.pop(u, None)
            USER_LAST_TS.pop(u, None)
        if stale:
            logger.info(f"🧹 Cleaned {len(stale)} inactive sessions")

async def process_query(user_id: int, text: str) -> str:
    """Send short history + prompt → ChatGPT → return reply."""
    loop = asyncio.get_event_loop()
    now = loop.time()
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
        logger.exception("Unexpected error in LLM call")
        return "🚨 Unexpected server error."

    answer = getattr(resp, "message", None) or str(resp)
    hist.append({"role":"bot","content":answer})
    return answer

# ─── TELEGRAM BOT SETUP ────────────────────────────────────────
bot = Bot(token=BOT_TOKEN, parse_mode=ParseMode.MARKDOWN)
dp  = Dispatcher()

# ─── SELF-UPDATE / RESTART HANDLER ─────────────────────────────
@dp.message(F.chat.type == ChatType.PRIVATE, F.text.regexp(r"(?i)^jarvis restart$"))
async def restart_handler(msg: types.Message) -> None:
    """Pull latest code, install deps, summarise diff via GPT, then restart."""
    await msg.reply("⏳ Updating in background…")

    async def _do_update(chat_id: int):
        cwd = os.path.dirname(__file__)
        def run(cmd):
            return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)

        g = run(["git","pull"])
        if g.returncode:
            return await bot.send_message(chat_id, f"❌ Git pull failed:\n{g.stderr}")

        i = run(["pip3","install","-r","requirements.txt"])
        if i.returncode:
            return await bot.send_message(chat_id, f"❌ pip install failed:\n{i.stderr}")

        run(["pip3","install","--upgrade","safoneapi"])

        old = run(["git","rev-parse","HEAD@{1}"]).stdout.strip()
        new = run(["git","rev-parse","HEAD"]).stdout.strip()
        diff = run(["git","diff", old, new]).stdout.strip() or "No changes"

        prompt = (
            f"Master, here’s the diff {old[:7]}→{new[:7]}:\n{diff}\n\n"
            "Please summarise file-by-file, skipping trivial edits."
        )
        try:
            r = await api.chatgpt(prompt)
            summary = getattr(r, "message", str(r))
        except Exception as e:
            summary = f"⚠️ Summarisation failed: {e}"

        safe = f"```\n{summary[:3500]}\n```"
        await bot.send_message(chat_id, "✅ Update complete!\n\n" + safe)

        await shutdown()
        do_restart()

    asyncio.create_task(_do_update(msg.from_user.id))

# ─── PRE-RESTART GUARD ──────────────────────────────────────────
import threat   # verifies bot.py compiles before allowing restart

# ─── HELP & CHAT HANDLERS ──────────────────────────────────────
@dp.message(CommandStart(), F.chat.type == ChatType.PRIVATE)
async def cmd_start(msg: types.Message) -> None:
    await msg.answer("👋 Greetings, Master! Jarvis is online — just say anything.")

@dp.message(
    F.chat.type == ChatType.PRIVATE,
    F.text.regexp(r"(?i)^(help|help me|what can you do)\??$")
)
async def help_cmd(msg: types.Message) -> None:
    await msg.reply(
        "🤖 I’m Jarvis! You can:\n"
        "• Chat naturally—no slash commands\n"
        "• “Jarvis restart” to self-update\n"
        "• “Jarvis logs” for AI-driven error analysis\n"
        "• Inline +888… for fragment URLs\n"
        "• “Jarvis review code” for AI suggestions\n"
    )

@dp.message(
    F.chat.type == ChatType.PRIVATE,
    F.text,
    ~F.text.regexp(r"(?i)^(jarvis restart|jarvis logs|jarvis review code)$")
)
async def chat_handler(msg: types.Message) -> None:
    try:
        start = perf_counter()
        reply = await process_query(msg.from_user.id, msg.text.strip())
        elapsed = perf_counter() - start
        await msg.reply(f"{reply}\n\n⏱️ {elapsed:.2f}s")
    except Exception:
        logger.exception("Error in chat handler")
        await msg.reply("🚨 Unexpected error. Try again.")

# ─── PLUGIN AUTO-LOAD ──────────────────────────────────────────
PLUGIN_MODULES = ["fragment_url", "logs_utils", "code_review"]
_loaded = []
for mod in PLUGIN_MODULES:
    try:
        __import__(mod)
        _loaded.append(mod)
        logger.info(f"✅ Plugin loaded: {mod}")
    except Exception as e:
        logger.error(f"❌ Plugin `{mod}` failed to load: {e}")
        if MASTER_ID:
            asyncio.create_task(
                bot.send_message(MASTER_ID, f"⚠️ Plugin `{mod}` load error:\n{e}")
            )
logger.info(f"Active plugins: {_loaded}")

# ─── SCHEDULE MEMORY CLEANUP ───────────────────────────────────
loop = asyncio.get_event_loop()
loop.create_task(memory_cleanup())

# ─── RUN POLLING ───────────────────────────────────────────────
if __name__ == "__main__":
    dp.run_polling(bot, skip_updates=True)
