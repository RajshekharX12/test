import os
import html
import uuid
import logging
import asyncio
from aiogram import Bot, Dispatcher, types, F
from aiogram.enums import ParseMode, ChatType
-from aiogram.types import ChatActions
+from aiogram.enums.chat_action import ChatAction  # :contentReference[oaicite:1]{index=1}
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

PROMPT_INTRO = (
    "You are the user's friend. Reply in friendly Hindi with emojis, "
    "using 'bhai' style words like 'Arey bhai', 'Nahi bhai', etc.\n\n"
)

async def process_query(user_id: int, query: str) -> str:
    """Append query to history, build prompt, call SafoneAPI, update history, return answer."""
    history = conversation_histories.get(user_id, [])
    history.append({"role": "user", "content": query})

    lines = [PROMPT_INTRO] + [
        f"{'User:' if msg['role']=='user' else 'Bot:'} {msg['content']}"
        for msg in history
    ]
    prompt = "\n".join(lines)

    resp = await api.chatgpt(prompt)
    answer = resp.message or "Kuch toh gadbad hai, jawab nahi mila."

    history.append({"role": "bot", "content": answer})
    if len(history) > MAX_HISTORY_PAIRS * 2:
        del history[:-MAX_HISTORY_PAIRS * 2]
    conversation_histories[user_id] = history

    return answer

async def keep_typing(chat_id: int, stop_event: asyncio.Event):
    """Keep sending ChatAction.TYPING until stop_event is set."""
    while not stop_event.is_set():
        await bot.send_chat_action(chat_id, ChatAction.TYPING)  # :contentReference[oaicite:2]{index=2}
        await asyncio.sleep(4)

# ─── /start HANDLER ────────────────────────────────────────────
@dp.message(CommandStart())
async def start(message: types.Message):
    await message.answer("👋 Bhai, bas yahan message likho, main yaad rakhunga aur reply dunga!")

# ─── PRIVATE CHAT HANDLER ─────────────────────────────────────
@dp.message(F.chat.type == ChatType.PRIVATE, F.text)
async def private_message_handler(message: types.Message):
    stop_event = asyncio.Event()
    typer = asyncio.create_task(keep_typing(message.chat.id, stop_event))

    try:
        status = await message.reply("🧠 Generating answer...")
        answer = await process_query(message.from_user.id, message.text)
        await status.edit_text(html.escape(answer))
    except Exception:
        logger.exception("Error in private_message_handler")
        await status.edit_text("🚨 Koi internal error hua. Dobara try karo.")
    finally:
        stop_event.set()
        await typer

# ─── INLINE QUERY HANDLER ─────────────────────────────────────
@dp.inline_query()
async def inline_query_handler(inline_q: types.InlineQuery):
    query = inline_q.query.strip()
    if not query:
        return

    try:
        answer = await process_query(inline_q.from_user.id, query)
        safe = html.escape(answer)
        result = types.InlineQueryResultArticle(
            id=str(uuid.uuid4()),
            title="Bhai ka jawab",
            description=(safe[:50] + "...") if len(safe) > 50 else safe,
            input_message_content=types.InputTextMessageContent(
                safe, parse_mode=ParseMode.HTML
            ),
        )
        await bot.answer_inline_query(
            inline_q.id, results=[result], cache_time=0, is_personal=True
        )
    except Exception:
        logger.exception("Error in inline_query_handler")
        # fail silently

# ─── MAIN ─────────────────────────────────────────────────────
if __name__ == "__main__":
    logger.info("🚀 Bot is starting with typing indicators…")
    dp.run_polling(bot)


