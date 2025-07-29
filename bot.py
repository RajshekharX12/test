import os
import html
import uuid
import logging
from aiogram import Bot, Dispatcher, types, F
from aiogram.enums import ParseMode, ChatType
from aiogram.filters import CommandStart
from SafoneAPI import SafoneAPI
from dotenv import load_dotenv

# ─── LOAD ENV ─────────────────────────────────────────────────
load_dotenv()
API_TOKEN = os.getenv("BOT_TOKEN")
if not API_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set in .env")

# ─── LOGGING ──────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# ─── BOT & API SETUP ──────────────────────────────────────────
bot = Bot(token=API_TOKEN, parse_mode=ParseMode.HTML)
dp = Dispatcher()
api = SafoneAPI()

# ─── MEMORY CONFIG ────────────────────────────────────────────
# Holds a list of {"role": "user"|"bot", "content": str} per user_id
conversation_histories: dict[int, list[dict[str,str]]] = {}
MAX_HISTORY_PAIRS = 10

# Instruction prefixed to every prompt
PROMPT_INTRO = (
    "You are the user's friend. Reply in friendly Hindi with emojis, "
    "using 'bhai' style words like 'Arey bhai', 'Nahi bhai', etc.\n\n"
)

async def process_query(user_id: int, query: str) -> str:
    """Calls SafoneAPI.chatgpt with conversation history + new query."""
    history = conversation_histories.get(user_id, [])
    # Append the new user message
    history.append({"role": "user", "content": query})
    # Build a single string prompt
    lines = [PROMPT_INTRO]
    for msg in history:
        prefix = "User:" if msg["role"] == "user" else "Bot:"
        lines.append(f"{prefix} {msg['content']}")
    prompt = "\n".join(lines)

    # Call the API
    resp = await api.chatgpt(prompt)
    answer = resp.message or "Kuch toh gadbad hai, jawab nahin mila."

    # Append bot's answer to history
    history.append({"role": "bot", "content": answer})
    # Trim history if too long
    if len(history) > MAX_HISTORY_PAIRS * 2:
        history = history[-MAX_HISTORY_PAIRS * 2 :]
    conversation_histories[user_id] = history

    return answer

# ─── /start ───────────────────────────────────────────────────
@dp.message(CommandStart())
async def start(message: types.Message):
    await message.answer(
        "👋 Bhai, bas yahan message likho, main yaad rakhunga aur reply dunga!"
    )

# ─── PRIVATE CHAT HANDLER ──────────────────────────────────────
@dp.message(F.chat.type == ChatType.PRIVATE, F.text)
async def private_message_handler(message: types.Message):
    status = await message.reply("🧠 Generating answer...")
    try:
        answer = await process_query(message.from_user.id, message.text)
        safe = html.escape(answer)
        await status.edit_text(safe)
    except Exception:
        logger.exception("Error in private_message_handler")
        await status.edit_text("🚨 Koi internal error hua. Dobara try karo.")

# ─── INLINE MODE HANDLER ───────────────────────────────────────
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
            input_message_content=types.InputTextMessageContent(
                safe, parse_mode=ParseMode.HTML
            ),
            description=(safe[:50] + "...") if len(safe) > 50 else safe
        )
        await bot.answer_inline_query(
            inline_q.id, results=[result], cache_time=0, is_personal=True
        )
    except Exception:
        logger.exception("Error in inline_query_handler")
        # Fail silently (no results)

# ─── RUN BOT ──────────────────────────────────────────────────
if __name__ == "__main__":
    logger.info("🚀 Bot is starting with inline & memory support...")
    dp.run_polling(bot)


