import os
import re
import logging
import asyncio
import random
import httpx

from aiogram import Bot, Dispatcher, types, F
from aiogram.enums import ParseMode, ChatType
from aiogram.enums.chat_action import ChatAction
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
conversation_histories: dict[int, list[dict[str, str]]] = {}

SYSTEM_PROMPT = (
    "You are Jarvis, a professional AI assistant. "
    "The user is your master. Respond helpfully in friendly English with emojis.\n\n"
)

# ─── FUN STATUS MESSAGES ───────────────────────────────────────
STATUS_MESSAGES = [
    "🤖 Jarvis is charging its gears...",
    "😴 Jarvis is catching some zzz...",
    "🐢 Jarvis is in turtle mode, please wait...",
    "🍕 Jarvis is grabbing a slice, hang tight...",
    "🎯 Jarvis is locking onto the target...",
    "🚀 Jarvis is fueling up thrusters...",
    "🦾 Jarvis is flexing its robotic arm...",
    "🎩 Jarvis is pulling a rabbit out of a hat...",
    "🔍 Jarvis is magnifying clues...",
    "🎵 Jarvis is humming a tune..."
]

# ─── HELPERS ───────────────────────────────────────────────────
async def process_query(user_id: int, text: str) -> str:
    """Append to memory, build prompt, call ChatGPT with retry, update memory."""
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
            # retry with only last user message
            last = history[-1]
            history.clear()
            history.append(last)
            prompt = SYSTEM_PROMPT + f"Master: {last['content']}\n"
            resp = await api.chatgpt(prompt)
        else:
            raise

    answer = resp.message or "I'm sorry, something went wrong."
    history.append({"role": "bot", "content": answer})
    return answer

async def keep_typing(chat_id: int, stop_evt: asyncio.Event):
    """Keep the 'typing' indicator alive."""
    while not stop_evt.is_set():
        await bot.send_chat_action(chat_id, ChatAction.TYPING)
        await asyncio.sleep(4)

def pick_status() -> str:
    """Choose a random fun status message."""
    return random.choice(STATUS_MESSAGES)

# ─── HANDLERS ──────────────────────────────────────────────────
@dp.message(CommandStart(), F.chat.type == ChatType.PRIVATE)
async def cmd_start(message: types.Message):
    await message.answer(
        "👋 Hello, Master! I'm Jarvis—send me text, documents, or photos, "
        "and I'll remember everything and help out."
    )

@dp.message(F.chat.type == ChatType.PRIVATE, F.text)
async def dm_handler(message: types.Message):
    user_id = message.from_user.id
    text = message.text.strip()
    if not text:
        return

    # record user message
    conversation_histories.setdefault(user_id, []).append({"role": "user", "content": text})

    # send a random status
    status = await message.reply(pick_status())
    stop_evt = asyncio.Event()
    typer = asyncio.create_task(keep_typing(message.chat.id, stop_evt))

    try:
        answer = await process_query(user_id, text)
        await status.edit_text(answer, parse_mode=None)
    finally:
        stop_evt.set()
        await typer

@dp.message(F.chat.type == ChatType.PRIVATE, F.document)
async def document_handler(message: types.Message):
    doc = message.document
    user_id = message.from_user.id
    conversation_histories.setdefault(user_id, []).append({
        "role": "user", "content": f"<Document {doc.file_name}>"
    })

    file = await bot.get_file(doc.file_id)
    url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file.file_path}"

    status = await message.reply(pick_status())
    stop_evt = asyncio.Event()
    typer = asyncio.create_task(keep_typing(message.chat.id, stop_evt))

    try:
        prompt = f"Please analyze the content of the document at this URL:\n{url}"
        answer = await process_query(user_id, prompt)
        await status.edit_text(answer, parse_mode=None)
        conversation_histories[user_id].append({"role": "bot", "content": answer})
    finally:
        stop_evt.set()
        await typer

@dp.message(F.chat.type == ChatType.PRIVATE, F.photo)
async def photo_handler(message: types.Message):
    photo = message.photo[-1]
    user_id = message.from_user.id
    conversation_histories.setdefault(user_id, []).append({
        "role": "user", "content": "<Photo>"
    })

    file = await bot.get_file(photo.file_id)
    url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file.file_path}"

    status = await message.reply(pick_status())
    stop_evt = asyncio.Event()
    typer = asyncio.create_task(keep_typing(message.chat.id, stop_evt))

    try:
        prompt = f"Please describe and interpret the image at this URL:\n{url}"
        answer = await process_query(user_id, prompt)
        await status.edit_text(answer, parse_mode=None)
        conversation_histories[user_id].append({"role": "bot", "content": answer})
    finally:
        stop_evt.set()
        await typer

# ─── MAIN ─────────────────────────────────────────────────────
if __name__ == "__main__":
    logger.info("🚀 Jarvis is starting with fun status messages…")
    dp.run_polling(bot)
