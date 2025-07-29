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

# ─── STATE & MEMORY ───────────────────────────────────────────
BOT_USERNAME = ""
conversation_histories: dict[int, list[dict[str,str]]] = {}
MAX_HISTORY_PAIRS = 10

PROMPT_INTRO = (
    "You are Jarvis, a professional AI assistant. "
    "The user is your master. You help with tasks—especially managing +888 rental numbers—"
    "and speak respectfully and concisely.\n\n"
)

async def on_startup():
    global BOT_USERNAME
    me = await bot.get_me()
    BOT_USERNAME = me.username or ""
    logger.info(f"🤖 Bot username: @{BOT_USERNAME}")

async def process_query(user_id: int, query: str) -> str:
    hist = conversation_histories.get(user_id, [])
    hist.append({"role":"user","content":query})
    lines = [PROMPT_INTRO] + [
        f"{'Master:' if m['role']=='user' else 'Jarvis:'} {m['content']}"
        for m in hist
    ]
    prompt = "\n".join(lines)
    resp = await api.chatgpt(prompt)
    ans = resp.message or "I apologize, Master—something went wrong."
    hist.append({"role":"bot","content":ans})
    if len(hist) > MAX_HISTORY_PAIRS*2:
        del hist[:-MAX_HISTORY_PAIRS*2]
    conversation_histories[user_id] = hist
    return ans

async def keep_typing(chat_id: int, stop_evt: asyncio.Event):
    while not stop_evt.is_set():
        await bot.send_chat_action(chat_id, ChatAction.TYPING)
        await asyncio.sleep(4)

# ─── /start ────────────────────────────────────────────────────
@dp.message(CommandStart())
async def cmd_start(msg: types.Message):
    await msg.answer(
        "👋 Greetings, Master. I am Jarvis. "
        "Type here in DMs or mention me in groups—I'll reply contextually."
    )

# ─── PRIVATE DM HANDLER ────────────────────────────────────────
@dp.message(F.chat.type==ChatType.PRIVATE, F.text)
async def private_handler(msg: types.Message):
    q = msg.text.strip()
    if not q: return

    stop = asyncio.Event()
    task = asyncio.create_task(keep_typing(msg.chat.id, stop))

    try:
        status = await msg.reply("🧠 Jarvis is thinking...")
        ans = await process_query(msg.from_user.id, q)
        await status.edit_text(html.escape(ans))
    except Exception:
        logger.exception("private_handler")
        await status.edit_text("🚨 My apologies, Master—an internal error occurred.")
    finally:
        stop.set()
        await task

# ─── GROUP MENTION HANDLER ────────────────────────────────────
@dp.message(
    F.chat.type.in_([ChatType.GROUP,ChatType.SUPERGROUP]),
    F.text.startswith(lambda _: f"@{BOT_USERNAME}")
)
async def group_handler(msg: types.Message):
    parts = msg.text.split(maxsplit=1)
    q = parts[1] if len(parts)>1 else ""
    if not q: return

    stop = asyncio.Event()
    task = asyncio.create_task(keep_typing(msg.chat.id, stop))
    try:
        st = await msg.reply("🧠 Jarvis is thinking...")
        ans = await process_query(msg.from_user.id, q)
        await st.edit_text(html.escape(ans))
    finally:
        stop.set()
        await task

# ─── INLINE QUERY HANDLER (5s TIMEOUT SAFE) ───────────────────
@dp.inline_query()
async def inline_handler(iq: types.InlineQuery):
    user = iq.from_user.id
    q = iq.query.strip()
    if not q: return

    results: list[types.InlineQueryResultArticle] = []
    try:
        # Wait up to 4 seconds for a live answer
        ans = await asyncio.wait_for(process_query(user, q), timeout=4)
        safe = html.escape(ans)
        snippet = (safe[:100]+"...") if len(safe)>100 else safe
        results.append(types.InlineQueryResultArticle(
            id="live",
            title="Jarvis replies:",
            description=snippet,
            input_message_content=types.InputTextMessageContent(
                message_text=safe,
                parse_mode=ParseMode.HTML
            )
        ))
    except asyncio.TimeoutError:
        # Fallback: prompt user to switch to private chat
        results.append(types.InlineQueryResultArticle(
            id="dm",
            title="Ask Jarvis in DM",
            description="Preview unavailable—tap to ask privately",
            input_message_content=types.InputTextMessageContent(
                message_text=q
            ),
            switch_pm_text="Ask Jarvis",
            switch_pm_parameter="start"
        ))
    except Exception:
        logger.exception("inline_handler")
        # silent fail

    await bot.answer_inline_query(
        iq.id,
        results=results,
        cache_time=0,
        is_personal=True
    )

# ─── MAIN ─────────────────────────────────────────────────────
if __name__ == "__main__":
    dp.run_polling(bot, on_startup=[on_startup])
