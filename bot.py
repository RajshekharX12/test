import os
import re
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
logger = logging.getLogger(__name__)

# ─── HTTP CLIENT & API ─────────────────────────────────────────
http_client = httpx.AsyncClient(timeout=10)
api = SafoneAPI()  # assuming default uses shared client internally

# ─── MEMORY CONFIG ─────────────────────────────────────────────
# keep only last 6 messages per user for speed
MAX_HISTORY = 6
conversation_histories: dict[int, deque[dict[str, str]]] = {}

SYSTEM_PROMPT = (
    "You are Jarvis, a professional AI assistant. "
    "The user is your master. Respond helpfully in friendly English with emojis.\n\n"
)

# ─── INTENT MAP ─────────────────────────────────────────────────
INTENT_MAP = {
    "technical": "chatgpt",
    "creative":  "gemini",
    "marketing": "gemini",
    "privacy":   "llama3",
    "factual":   "asq",
    "summary":   "chatgpt",
    "ideation":  "gemini",
}

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

# ─── CORE QUERY PROCESSING ────────────────────────────────────
async def process_query(user_id: int, text: str) -> str:
    history = conversation_histories.setdefault(user_id, deque(maxlen=MAX_HISTORY))
    history.append({"role": "user", "content": text})

    prompt = SYSTEM_PROMPT + ''.join(
        f"{'Master:' if m['role']=='user' else 'Jarvis:'} {m['content']}\n"
        for m in history
    )

    intent = detect_intent(text)
    endpoint = INTENT_MAP.get(intent, "chatgpt")
    api_call = getattr(api, endpoint, api.chatgpt)

    try:
        resp = await api_call(prompt)
    except GenericApiError as e:
        if "reduce the context" in str(e).lower():
            last = history[-1]
            conversation_histories[user_id] = deque([last], maxlen=MAX_HISTORY)
            retry_prompt = SYSTEM_PROMPT + f"Master: {last['content']}\n"
            resp = await api_call(retry_prompt)
        else:
            raise

    answer = getattr(resp, 'message', None) or str(resp)
    history.append({"role": "bot", "content": answer})
    return answer

# ─── BOT SETUP & HANDLERS ─────────────────────────────────────
bot = Bot(token=BOT_TOKEN, parse_mode=ParseMode.MARKDOWN)
dp = Dispatcher()

@dp.message(CommandStart(), F.chat.type == ChatType.PRIVATE)
async def cmd_start(message: types.Message):
    await message.answer(
        "👋 Hello, Master! I'm Jarvis v1.0.69—type or send anything, and I'll reply quickly and remember the last few messages."
    )

@dp.message(F.chat.type == ChatType.PRIVATE, F.text)
async def text_handler(message: types.Message):
    answer = await process_query(message.from_user.id, message.text.strip())
    await message.reply(answer)

@dp.message(F.chat.type == ChatType.PRIVATE, F.document)
async def document_handler(message: types.Message):
    user_id = message.from_user.id
    doc = message.document
    file = await bot.get_file(doc.file_id)
    data = await bot.download_file(file.file_path)

    history = conversation_histories.setdefault(user_id, deque(maxlen=MAX_HISTORY))
    history.append({"role": "user", "content": f"<Document {doc.file_name}>"})

    ocr = getattr(api, 'ocr_text_scanner', None) or getattr(api, 'document_ocr', None)
    if not ocr:
        return await message.reply("⚠️ Document analysis API not available.")
    resp = await ocr(data)
    summary = getattr(resp, 'summary', None) or getattr(resp, 'text', None) or str(resp)

    history.append({"role": "bot", "content": summary})
    await message.reply(summary)

@dp.message(F.chat.type == ChatType.PRIVATE, F.photo)
async def photo_handler(message: types.Message):
    user_id = message.from_user.id
    photo = message.photo[-1]
    file = await bot.get_file(photo.file_id)
    data = await bot.download_file(file.file_path)

    history = conversation_histories.setdefault(user_id, deque(maxlen=MAX_HISTORY))
    history.append({"role": "user", "content": "<Photo>"})

    recog = getattr(api, 'image_recognition', None) or getattr(api, 'ocr_text_scanner', None)
    if not recog:
        return await message.reply("⚠️ Image analysis API not available.")
    resp = await recog(data)
    description = getattr(resp, 'description', None) or getattr(resp, 'text', None) or str(resp)

    history.append({"role": "bot", "content": description})
    await message.reply(description)

# ─── MAIN ─────────────────────────────────────────────────────
async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    logger.info("🚀 Jarvis started: fast mode with capped history.")
    await dp.start_polling(bot, skip_updates=True)

if __name__ == '__main__':
    asyncio.run(main())

