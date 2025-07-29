import os
import re
import logging
import asyncio
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

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# ─── BOT & API SETUP ───────────────────────────────────────────
bot = Bot(token=BOT_TOKEN, parse_mode=ParseMode.MARKDOWN)
dp = Dispatcher()
api = SafoneAPI()

# ─── MEMORY ────────────────────────────────────────────────────
conversation_histories: dict[int, list[dict[str, str]]] = {}

SYSTEM_PROMPT = (
    "You are Jarvis, a professional AI assistant. "
    "The user is your master. Respond helpfully in friendly English with emojis.\n\n"
)

# ─── CORE HELPERS ──────────────────────────────────────────────
async def process_query(user_id: int, text: str) -> str:
    """Append to memory, build prompt, call ChatGPT with context trimming, update memory."""
    history = conversation_histories.setdefault(user_id, [])
    history.append({"role": "user", "content": text})

    def build_prompt():
        return SYSTEM_PROMPT + "".join(
            f"{'Master:' if m['role']=='user' else 'Jarvis:'} {m['content']}\n"
            for m in history
        )

    prompt = build_prompt()
    try:
        resp = await api.chatgpt(prompt)
    except GenericApiError as e:
        if "reduce the context" in str(e).lower():
            last = history[-1]
            conversation_histories[user_id] = [last]
            prompt = SYSTEM_PROMPT + f"Master: {last['content']}\n"
            resp = await api.chatgpt(prompt)
        else:
            raise

    answer = resp.message or "I'm sorry, something went wrong."
    history.append({"role": "bot", "content": answer})
    return answer

# ─── HANDLERS ──────────────────────────────────────────────────
@dp.message(CommandStart(), F.chat.type == ChatType.PRIVATE)
async def cmd_start(message: types.Message):
    await message.answer(
        "👋 Hello, Master! I'm Jarvis—send me text, documents, or photos, and I'll remember everything and help."
    )

@dp.message(F.chat.type == ChatType.PRIVATE, F.text)
async def text_handler(message: types.Message):
    user_id = message.from_user.id
    text = message.text.strip()
    if not text:
        return

    answer = await process_query(user_id, text)
    await message.reply(answer)

@dp.message(F.chat.type == ChatType.PRIVATE, F.document)
async def document_handler(message: types.Message):
    doc = message.document
    user_id = message.from_user.id

    # download document bytes
    file = await bot.get_file(doc.file_id)
    doc_bytes = await bot.download_file(file.file_path)

    prompt = "Please analyze the content of this document and summarize it."
    # record the document event
    history = conversation_histories.setdefault(user_id, [])
    history.append({"role": "user", "content": f"<Document {doc.file_name}>"})

    # send to vision endpoint
    resp = await api.vision.analyze_document(doc_bytes)  # adjust method name as needed
    summary = resp.summary if hasattr(resp, "summary") else resp.description

    history.append({"role": "bot", "content": summary})
    await message.reply(summary)

@dp.message(F.chat.type == ChatType.PRIVATE, F.photo)
async def photo_handler(message: types.Message):
    photo = message.photo[-1]
    user_id = message.from_user.id

    # download image bytes
    file = await bot.get_file(photo.file_id)
    img_bytes = await bot.download_file(file.file_path)

    prompt = "Please describe and interpret this image."
    # record the photo event
    history = conversation_histories.setdefault(user_id, [])
    history.append({"role": "user", "content": "<Photo>"})

    # send to vision endpoint
    resp = await api.vision.describe_image(img_bytes)
    description = resp.description

    history.append({"role": "bot", "content": description})
    await message.reply(description)

# ─── MAIN ─────────────────────────────────────────────────────
if __name__ == "__main__":
    logger.info("🚀 Jarvis is starting—no status messages, full memory, vision enabled.")
    dp.run_polling(bot)
