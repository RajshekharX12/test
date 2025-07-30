#!/usr/bin/env python3
"""
Jarvis v1.0.69 — Respectful, resilient Telegram AI assistant with on‑the‑fly updates

Features:
 • Always address you as Master/Sir/Chief
 • ChatGPT‑only AI via SafoneAPI.chatgpt(prompt)
 • Full in‑memory conversation history (with inactivity pruning)
 • Natural “help” trigger
 • “Jarvis restart” pulls latest code, shows stats & diff, then hot‑restarts
 • Graceful shutdown of HTTP & bot sessions
 • Response time appended to every reply

Dependencies (requirements.txt):
 aiogram==3.4.1
 safoneapi==1.0.69
 python-dotenv>=1.0.0
 httpx>=0.24.0
 tgcrypto      # optional speedup
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
from SafoneAPI import SafoneAPI, errors as safone_errors
from dotenv import load_dotenv

# ─── ENV & LOGGING ─────────────────────────────────────────────────
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
if not BOT_TOKEN:
    raise RuntimeError("❌ BOT_TOKEN is not set in .env")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("jarvis")

# ─── API CLIENT & SHUTDOWN ─────────────────────────────────────────
api = SafoneAPI()  # ChatGPT-only
http_client = httpx.AsyncClient(timeout=10)

async def shutdown() -> None:
    """Cleanly close HTTP client and bot session."""
    logger.info("🔌 Shutting down HTTP client and bot session...")
    await http_client.aclose()
    await bot.session.close()
    logger.info("✅ Shutdown complete.")

def do_restart() -> None:
    """Re-executes this script with the same Python interpreter."""
    python = sys.executable
    os.execv(python, [python] + sys.argv)

# ─── MEMORY & INACTIVITY CLEANUP ──────────────────────────────────
HISTORY: Dict[int, Deque[Dict[str, str]]] = defaultdict(lambda: deque())
LAST_ACTIVE: Dict[int, datetime] = {}
MIN_INTERVAL = 1.0                      # sec between messages per user
INACTIVITY_LIMIT = timedelta(hours=1)  # clear after 1h idle

async def clean_inactive_users() -> None:
    """Periodically purge memory of users inactive >1h."""
    while True:
        await asyncio.sleep(600)
        cutoff = datetime.utcnow() - INACTIVITY_LIMIT
        for uid, ts in list(LAST_ACTIVE.items()):
            if ts < cutoff:
                HISTORY.pop(uid, None)
                LAST_ACTIVE.pop(uid, None)
                logger.info(f"🧹 Cleared memory for inactive Master {uid}")

# ─── CORE AI CALL ─────────────────────────────────────────────────
async def process_query(user_id: int, text: str) -> str:
    """Build respectful prompt, call ChatGPT, handle errors, record history."""
    # Rate‑limit
    now_ts = asyncio.get_event_loop().time()
    last_ts = LAST_ACTIVE.get(user_id, datetime.utcnow()).timestamp()
    if now_ts - last_ts < MIN_INTERVAL:
        await asyncio.sleep(MIN_INTERVAL - (now_ts - last_ts))
    LAST_ACTIVE[user_id] = datetime.utcnow()

    # Append to history
    hist = HISTORY[user_id]
    hist.append({"role": "user", "content": text})

    # Help trigger
    if any(kw in text.lower() for kw in ("help", "what can you do", "how to use")):
        return (
            "🤖 *Jarvis Help*\n"
            " • Just type any question—no prefix needed.\n"
            " • I address you as Master/Sir/Chief.\n"
            " • I remember our chat & show response times.\n"
            " • Say “Jarvis restart” to pull updates & reboot.\n"
        )

    # Build respectful system prompt + history
    prompt = (
        "You are Jarvis, a dutiful AI assistant. "
        "Always address the user respectfully as Master, Sir, or Chief.\n\n"
    )
    for msg in hist:
        speaker = "Master" if msg["role"] == "user" else "Jarvis"
        prompt += f"{speaker}: {msg['content']}\n"
    prompt += "Jarvis:"

    # Call ChatGPT endpoint
    try:
        resp = await api.chatgpt(prompt)
    except safone_errors.GenericApiError as e:
        if "reduce the context" in str(e).lower() and hist:
            last_msg = hist[-1]
            hist.clear()
            hist.append(last_msg)
            retry = f"Master: {last_msg['content']}\nJarvis:"
            resp = await api.chatgpt(retry)
        else:
            logger.error(f"ChatGPT API error: {e}")
            return "🚨 Master, I encountered an AI service error. Please try again."
    except Exception as e:
        logger.exception("Unexpected error in AI call")
        return f"🚨 Master, something went wrong: {type(e).__name__}"

    answer = getattr(resp, "message", None) or str(resp)
    hist.append({"role": "bot", "content": answer})
    return answer

# ─── BOT SETUP & HANDLERS ────────────────────────────────────────
bot = Bot(token=BOT_TOKEN, parse_mode=ParseMode.MARKDOWN)
dp  = Dispatcher()

@dp.message(CommandStart(), F.chat.type == ChatType.PRIVATE)
async def cmd_start(msg: types.Message) -> None:
    await msg.answer("👋 Greetings, Master! Jarvis is at your service. Speak, and I shall obey.")

# — Restart + Git‑Pull + Diff + Self‑Restart —
@dp.message(F.chat.type == ChatType.PRIVATE, F.text.regexp(r"(?i)^jarvis restart$"))
async def restart_handler(msg: types.Message) -> None:
    await msg.reply("🔄 Pulling latest code from Git, Master…")

    cwd = os.path.dirname(__file__)

    # 1) Old HEAD
    proc_old = await asyncio.create_subprocess_exec(
        "git", "rev-parse", "HEAD",
        stdout=asyncio.subprocess.PIPE,
        cwd=cwd
    )
    out_old, _ = await proc_old.communicate()
    old = out_old.decode().strip()

    # 2) Git pull
    proc_pull = await asyncio.create_subprocess_exec(
        "git", "pull",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd
    )
    out_pull, err_pull = await proc_pull.communicate()
    pull_out = out_pull.decode().strip()
    pull_err = err_pull.decode().strip()

    # 3) New HEAD
    proc_new = await asyncio.create_subprocess_exec(
        "git", "rev-parse", "HEAD",
        stdout=asyncio.subprocess.PIPE,
        cwd=cwd
    )
    out_new, _ = await proc_new.communicate()
    new = out_new.decode().strip()

    # 4) Diff‑stat summary
    proc_stat = await asyncio.create_subprocess_exec(
        "git", "diff", "--stat", old, new,
        stdout=asyncio.subprocess.PIPE,
        cwd=cwd
    )
    stat_out, _ = await proc_stat.communicate()
    stat = stat_out.decode().strip()

    # 5) Diff snippet (first 3000 chars)
    proc_diff = await asyncio.create_subprocess_exec(
        "git", "diff", old, new,
        stdout=asyncio.subprocess.PIPE,
        cwd=cwd
    )
    diff_out, _ = await proc_diff.communicate()
    diff_text = diff_out.decode()
    snippet = diff_text[:3000]

    # Reply with stats & snippet
    summary = stat or "✅ No changes pulled."
    await msg.reply(f"📦 Changes {old[:7]} → {new[:7]}:\n```{summary}```")
    if snippet:
        await msg.reply(f"🔍 Diff snippet:\n```{snippet}```")
        if len(diff_text) > len(snippet):
            await msg.reply("…and more lines omitted.")
    if pull_err:
        await msg.reply(f"⚠️ Git stderr:\n```{pull_err}```")

    # Pause, then restart
    await asyncio.sleep(1)
    await msg.reply("🔄 Restarting now, Master…")
    await shutdown()
    do_restart()

# — Catch‑all chat handler —
@dp.message(F.chat.type == ChatType.PRIVATE, F.text)
async def chat_handler(msg: types.Message) -> None:
    start = perf_counter()
    reply = await process_query(msg.from_user.id, msg.text.strip())
    elapsed = perf_counter() - start
    await msg.reply(f"{reply}\n\n⏱️ {elapsed:.2f}s")

# ─── MAIN & GRACEFUL SHUTDOWN ─────────────────────────────────────
async def main() -> None:
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda s=sig: asyncio.create_task(shutdown()))
    asyncio.create_task(clean_inactive_users())
    await bot.delete_webhook(drop_pending_updates=True)
    logger.info("🚀 Jarvis started: fetch‑and‑restart enabled.")
    await dp.start_polling(bot, skip_updates=True)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("👋 Master, Jarvis has been stopped by interruption.")
        asyncio.run(shutdown())
