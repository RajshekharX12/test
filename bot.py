import os
import html
import uuid
import logging
import asyncio

from aiogram import Bot, Dispatcher, types, F
from aiogram.enums import ParseMode, ChatType
from aiogram.enums.chat_action import ChatAction
from aiogram.filters import CommandStart
from SafoneAPI import SafoneAPI
from dotenv import load_dotenv

# ─── LOAD ENV ─────────────────────────────────────────────────
load_dotenv()
API_TOKEN = os.getenv("BOT_TOKEN")
if not API_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set in .env")

# ─── LOGGING ──────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# ─── BOT & API SETUP ──────────────────────────────────────────
bot = Bot(token=API_TOKEN, parse_mode=ParseMode.HTML)
dp = Dispatcher()
api = SafoneAPI()

# ─── MEMORY CONFIG ────────────────────────────────────────────
conversation_histories: dict[int, list[dict[str, str]]] = {}
MAX_HISTORY_PAIRS = 10

# ─── JARVIS PROMPT INTRO ──────────────────────────────────────
PROMPT_INTRO = (
    "You are Jarvis, a professional AI assistant. "
    "The user is your master. You help with tasks—especially managing +888 rental numbers—"
    "and speak respectfully and concisely.\n\n"
)

async def process_query(user_id: int, query: str) -> str:
    history = conversation_histories.get(user_id, [])
    history.append({"role": "user", "content": query})
    lines = [PROMPT_INTRO] + [
        f"{'Master:' if msg['role']=='user' else 'Jarvis:'} {msg['content']}"
        for msg in history
    ]
    prompt = "\n".join(lines)

    resp = await api.chatgpt(prompt)
    answer = resp.message or "I apologize, Master—something went wrong."

    history.append({"role": "bot", "content": answer})
    if len(history) > MAX_HISTORY_PAIRS * 2:
        del history[:-MAX_HISTORY_PAIRS * 2]
    conversation_histories[user_id] = history

    return answer

async def keep_typing(chat_id: int, stop_event: asyncio.Event):
    while not stop_event.is_set():
        await bot.send_chat_action(chat_id, ChatAction.TYPING)
        await asyncio.sleep(4)

# ─── /start ────────────────────────────────────────────────────
@dp.message(CommandStart())
async def start(message: types.Message):
    await message.answer(
        "👋 Greetings, Master. I am Jarvis. Just type your question or mention me inline, "
        "and I’ll respond—no slash or keyword needed."
    )

# ─── PRIVATE MESSAGE HANDLER ──────────────────────────────────
@dp.message(F.chat.type == ChatType.PRIVATE, F.text)
async def private_message_handler(message: types.Message):
    query = message.text.strip()
    if not query:
        return

    stop_event = asyncio.Event()
    typer = asyncio.create_task(keep_typing(message.chat.id, stop_event))
    try:
        status = await message.reply("🧠 Jarvis is thinking...")
        answer = await process_query(message.from_user.id, query)
        await status.edit_text(html.escape(answer))
    except Exception:
        logger.exception("Error in private_message_handler")
        await status.edit_text("🚨 My apologies, Master—an internal error occurred.")
    finally:
        stop_event.set()
        await typer

# ─── INLINE QUERY HANDLER (FIXED) ─────────────────────────────
@dp.inline_query()
async def inline_query_handler(inline_q: types.InlineQuery):
    query = inline_q.query.strip()
    if not query:
        return

    # Return the query itself; private handler will process it after user taps
    result = types.InlineQueryResultArticle(
        id=str(uuid.uuid4()),
        title="Ask Jarvis this",
        description=(query[:50] + "...") if len(query) > 50 else query,
        input_message_content=types.InputTextMessageContent(
            message_text=query
        ),
    )
    await bot.answer_inline_query(
        inline_q.id,
        results=[result],
        cache_time=300,
        is_personal=True
    )

# ─── MAIN ─────────────────────────────────────────────────────
if __name__ == "__main__":
    logger.info("🚀 Jarvis is starting—no inline timeouts!")
    dp.run_polling(bot)


