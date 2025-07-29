import os
import re
import logging

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

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ─── BOT & API SETUP ───────────────────────────────────────────
bot = Bot(token=BOT_TOKEN, parse_mode=ParseMode.MARKDOWN)
dp = Dispatcher()
api = SafoneAPI()

# ─── MEMORY ────────────────────────────────────────────────────
conversation_histories: dict[int, list[dict[str,str]]] = {}

SYSTEM_PROMPT = (
    "You are Jarvis, a professional AI assistant. "
    "The user is your master. Respond helpfully in friendly English with emojis.\n\n"
)

# ─── CORE HELPER ───────────────────────────────────────────────
async def process_query(user_id: int, text: str) -> str:
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
    user_id = message.from_user.id
    doc = message.document

    # download document bytes
    file = await bot.get_file(doc.file_id)
    doc_bytes = await bot.download_file(file.file_path)

    # record in memory
    conversation_histories.setdefault(user_id, []).append({
        "role": "user", "content": f"<Document {doc.file_name}>"
    })

    # pick an OCR/vision method if available
    ocr = getattr(api, "ocr_text_scanner", None) or getattr(api, "document_ocr", None)
    if not ocr:
        return await message.reply("⚠️ Document analysis API not available.")
    resp = await ocr(doc_bytes)
    summary = getattr(resp, "summary", None) or getattr(resp, "text", None) or str(resp)

    conversation_histories[user_id].append({"role": "bot", "content": summary})
    await message.reply(summary)

@dp.message(F.chat.type == ChatType.PRIVATE, F.photo)
async def photo_handler(message: types.Message):
    user_id = message.from_user.id
    photo = message.photo[-1]

    # download image bytes
    file = await bot.get_file(photo.file_id)
    img_bytes = await bot.download_file(file.file_path)

    # record in memory
    conversation_histories.setdefault(user_id, []).append({
        "role": "user", "content": "<Photo>"
    })

    # pick an image-recognition method if available
    recog = getattr(api, "image_recognition", None) or getattr(api, "ocr_text_scanner", None)
    if not recog:
        return await message.reply("⚠️ Image analysis API not available.")
    resp = await recog(img_bytes)
    description = getattr(resp, "description", None) or getattr(resp, "text", None) or str(resp)

    conversation_histories[user_id].append({"role": "bot", "content": description})
    await message.reply(description)

# ─── MAIN ─────────────────────────────────────────────────────
if __name__ == "__main__":
    logger.info("🚀 Jarvis started: full-memory chat + file/photo analysis.")
    dp.run_polling(bot)

