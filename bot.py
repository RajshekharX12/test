#!/usr/bin/env python3
"""
Jarvis v1.0.69 — full-memory chat + vision + in‑memory error logging
"""

import os
import re
import logging
import asyncio

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

# ─── SETUP ─────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("jarvis")

bot = Bot(token=BOT_TOKEN, parse_mode=ParseMode.MARKDOWN)
dp  = Dispatcher()
api = SafoneAPI()

# ─── IN‑MEMORY STORAGE ─────────────────────────────────────────
conversation_histories: dict[int, list[dict[str,str]]] = {}
error_logs: list[str] = []  # store timestamped error messages

SYSTEM_PROMPT = (
    "You are Jarvis, a professional AI assistant. "
    "The user is your master. Respond helpfully in friendly English with emojis.\n\n"
)

INTENT_MAP = {
    "technical": "chatgpt",
    "creative":  "gemini",
    "marketing": "gemini",
    "privacy":   "llama3",
    "factual":   "asq",
    "summary":   "chatgpt",
    "ideation":  "gemini",
}

def log_error(exc: Exception):
    """Record an error with timestamp, trimming to last 100 entries."""
    entry = f"{asyncio.get_event_loop().time():.1f} ERROR: {type(exc).__name__}: {exc}"
    error_logs.append(entry)
    if len(error_logs) > 100:
        error_logs.pop(0)

def detect_intent(text: str) -> str:
    txt = text.lower()
    if any(tok in txt for tok in ["debug", "error", "how", "why", "explain"]):
        return "technical"
    if txt.startswith(("write", "poem", "story", "compose")):
        return "creative"
    if txt.startswith(("sell", "advertise", "marketing", "slogan")):
        return "marketing"
    if any(tok in txt for tok in ["summarize", "tl;dr", "short"]):
        return "summary"
    if any(tok in txt for tok in ["idea", "brainstorm"]):
        return "ideation"
    if any(tok in txt for tok in ["who is", "what is", "where", "?"]):
        return "factual"
    return "technical"

async def process_query(user_id: int, text: str) -> str:
    history = conversation_histories.setdefault(user_id, [])
    history.append({"role":"user","content":text})

    prompt = SYSTEM_PROMPT + "".join(
        f"{'Master:' if m['role']=='user' else 'Jarvis:'} {m['content']}\n"
        for m in history
    )

    intent = detect_intent(text)
    endpoint = INTENT_MAP.get(intent, "chatgpt")
    api_call  = getattr(api, endpoint, api.chatgpt)

    try:
        resp = await api_call(prompt)
    except Exception as e:
        log_error(e)
        # on context error, retry with last message only
        if isinstance(e, GenericApiError) and "reduce the context" in str(e).lower():
            last = history[-1]
            conversation_histories[user_id] = [last]
            prompt = SYSTEM_PROMPT + f"Master: {last['content']}\n"
            try:
                resp = await api_call(prompt)
            except Exception as e2:
                log_error(e2)
                return f"🚨 Error after retry: {e2}"
        else:
            return f"🚨 Error processing your request: {e}"

    answer = getattr(resp, "message", None) or str(resp)
    history.append({"role":"bot","content":answer})
    return answer

@dp.message(CommandStart(), F.chat.type == ChatType.PRIVATE)
async def cmd_start(message: types.Message):
    await message.answer(
        "👋 Hello, Master! I'm Jarvis v1.0.69—type or send anything, and I'll remember it.\n"
        "Say “show me recent logs” to view my last errors."
    )

@dp.message(F.chat.type == ChatType.PRIVATE, F.text.regexp(r'(?i)\bshow (me )?recent logs\b'))
async def show_logs_handler(message: types.Message):
    # send up to last 20 error entries
    last = "\n".join(error_logs[-20:]) or "✅ No errors logged."
    # split to avoid Telegram limits
    for chunk in re.findall(r'.{1,3900}(?:\n|$)', last):
        await message.reply(f"```\n{chunk}```", parse_mode=ParseMode.MARKDOWN)

@dp.message(F.chat.type == ChatType.PRIVATE, F.text)
async def text_handler(message: types.Message):
    try:
        ans = await process_query(message.from_user.id, message.text.strip())
    except Exception as e:
        log_error(e)
        ans = f"🚨 Unexpected error: {e}"
    await message.reply(ans)

@dp.message(F.chat.type == ChatType.PRIVATE, F.document)
async def document_handler(message: types.Message):
    user_id = message.from_user.id
    doc     = message.document
    try:
        file = await bot.get_file(doc.file_id)
        data = await bot.download_file(file.file_path)

        conversation_histories.setdefault(user_id, []).append(
            {"role":"user","content":f"<Document {doc.file_name}>"}
        )

        ocr = getattr(api, "ocr_text_scanner", None) or getattr(api, "document_ocr", None)
        if not ocr:
            return await message.reply("⚠️ Document analysis API not available.")

        resp = await ocr(data)
        summary = getattr(resp, "summary", None) or getattr(resp, "text", None) or str(resp)
        conversation_histories[user_id].append({"role":"bot","content":summary})
        await message.reply(summary)

    except Exception as e:
        log_error(e)
        await message.reply(f"🚨 Error analyzing document: {e}")

@dp.message(F.chat.type == ChatType.PRIVATE, F.photo)
async def photo_handler(message: types.Message):
    user_id = message.from_user.id
    photo   = message.photo[-1]
    try:
        file = await bot.get_file(photo.file_id)
        data = await bot.download_file(file.file_path)

        conversation_histories.setdefault(user_id, []).append(
            {"role":"user","content":"<Photo>"}
        )

        recog = getattr(api, "image_recognition", None) or getattr(api, "ocr_text_scanner", None)
        if not recog:
            return await message.reply("⚠️ Image analysis API not available.")

        resp = await recog(data)
        desc = getattr(resp, "description", None) or getattr(resp, "text", None) or str(resp)
        conversation_histories[user_id].append({"role":"bot","content":desc})
        await message.reply(desc)

    except Exception as e:
        log_error(e)
        await message.reply(f"🚨 Error analyzing image: {e}")

async def main():
    # clear webhook / old updates
    await bot.delete_webhook(drop_pending_updates=True)
    logger.info("🚀 Jarvis started: full-memory + in‑memory error logs.")
    await dp.start_polling(bot, skip_updates=True)

if __name__ == "__main__":
    asyncio.run(main())
