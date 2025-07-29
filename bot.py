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

# ─── GLOBAL STATE ─────────────────────────────────────────────
BOT_USERNAME: str = ""
conversation_histories: dict[int, list[dict[str, str]]] = {}
MAX_HISTORY_PAIRS = 10

# ─── JARVIS PROMPT INTRO ──────────────────────────────────────
PROMPT_INTRO = (
    "You are Jarvis, a professional AI assistant. "
    "The user is your master. You help with tasks—especially managing +888 rental numbers—"
    "and speak respectfully and concisely.\n\n"
)

# ─── ON STARTUP: FETCH BOT USERNAME ────────────────────────────
async def on_startup():
    global BOT_USERNAME
    me = await bot.get_me()
    BOT_USERNAME = me.username or ""
    logger.info(f"🤖 Bot username: @{BOT_USERNAME}")

# ─── PROCESS QUERY & MEMORY ────────────────────────────────────
async def process_query(user_id: int, query: str) -> str:
    history = conversation_histories.get(user_id, [])
    history.append({"role": "user", "content": query})

    # build prompt
    lines = [PROMPT_INTRO] + [
        f"{'Master:' if msg['role']=='user' else 'Jarvis:'} {msg['content']}"
        for msg in history
    ]
    prompt = "\n".join(lines)

    # call API
    resp = await api.chatgpt(prompt)
    answer = resp.message or "I apologize, Master—something went wrong."

    # update history
    history.append({"role": "bot", "content": answer})
    if len(history) > MAX_HISTORY_PAIRS * 2:
        del history[:-MAX_HISTORY_PAIRS * 2]
    conversation_histories[user_id] = history

    return answer

# ─── TYPING INDICATOR ─────────────────────────────────────────
async def keep_typing(chat_id: int, stop_event: asyncio.Event):
    while not stop_event.is_set():
        await bot.send_chat_action(chat_id, ChatAction.TYPING)
        await asyncio.sleep(4)

# ─── /start ────────────────────────────────────────────────────
@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    await message.answer(
        "👋 Greetings, Master. I am Jarvis. "
        "Type here in DMs or mention me in groups—I'll reply contextually."
    )

# ─── PRIVATE DM HANDLER ────────────────────────────────────────
@dp.message(F.chat.type == ChatType.PRIVATE, F.text)
async def private_handler(message: types.Message):
    query = message.text.strip()
    if not query:
        return

    stop = asyncio.Event()
    task = asyncio.create_task(keep_typing(message.chat.id, stop))
    try:
        status = await message.reply("🧠 Jarvis is thinking...")
        answer = await process_query(message.from_user.id, query)
        await status.edit_text(html.escape(answer))
    finally:
        stop.set()
        await task

# ─── GROUP MENTION HANDLER ────────────────────────────────────
@dp.message(
    F.chat.type.in_([ChatType.GROUP, ChatType.SUPERGROUP]),
    F.text.startswith(lambda _: f"@{BOT_USERNAME}")
)
async def group_handler(message: types.Message):
    parts = message.text.split(maxsplit=1)
    query = parts[1] if len(parts) > 1 else ""
    if not query:
        return

    stop = asyncio.Event()
    task = asyncio.create_task(keep_typing(message.chat.id, stop))
    try:
        status = await message.reply("🧠 Jarvis is thinking...")
        answer = await process_query(message.from_user.id, query)
        await status.edit_text(html.escape(answer))
    finally:
        stop.set()
        await task

# ─── INLINE QUERY HANDLER (FAST & SAFE) ───────────────────────
@dp.inline_query()
async def inline_handler(inline_q: types.InlineQuery):
    user_id = inline_q.from_user.id
    query = inline_q.query.strip()
    if not query:
        return

    results: list[types.InlineQueryResultArticle] = []

    # 1) Check memory for a cached answer
    history = conversation_histories.get(user_id, [])
    snippet = None
    for i in range(len(history) - 1):
        if history[i]["role"] == "user" and history[i]["content"] == query:
            snippet = history[i + 1]["content"]
            break

    if snippet:
        safe = html.escape(snippet)
        desc = (safe[:100] + "...") if len(safe) > 100 else safe
        results.append(types.InlineQueryResultArticle(
            id="cached",
            title="Cached answer",
            description=desc,
            input_message_content=types.InputTextMessageContent(
                message_text=safe,
                parse_mode=ParseMode.HTML
            ),
        ))
    else:
        # 2) No cache → redirect to DM for live answer
        results.append(types.InlineQueryResultArticle(
            id="to_dm",
            title="Ask Jarvis in DM",
            description="No preview available—tap to ask in private chat",
            input_message_content=types.InputTextMessageContent(
                message_text=query
            ),
            switch_pm_text="Ask Jarvis",
            switch_pm_parameter="start"
        ))

    await bot.answer_inline_query(
        inline_q.id,
        results=results,
        cache_time=60,
        is_personal=True
    )

# ─── MAIN ─────────────────────────────────────────────────────
if __name__ == "__main__":
    dp.run_polling(bot, on_startup=[on_startup])
